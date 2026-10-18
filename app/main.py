import asyncio
import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE = Path(os.getenv('DATA_DIR', '/data')).resolve()
BASE.mkdir(parents=True, exist_ok=True)
MAX_BYTES = int(os.getenv('MAX_UPLOAD_MB', '150')) * 1024 * 1024
ALLOWED = {'.wav', '.mp3', '.flac', '.m4a', '.ogg', '.aiff', '.aif'}
app = FastAPI(title='Suno Audio Lab', version='1.0.0')
app.mount('/static', StaticFiles(directory=Path(__file__).parent / 'static'), name='static')


def run(args: list[str], timeout=240):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise RuntimeError('Audio processing timed out')
    if p.returncode:
        raise RuntimeError((p.stderr or 'ffmpeg failed')[-1800:])
    return p


def probe(path: Path):
    info = json.loads(run(['ffprobe','-v','error','-show_entries',
        'format=duration,format_name,bit_rate:format_tags:stream=codec_name,sample_rate,channels,channel_layout',
        '-select_streams','a:0','-of','json', str(path)], 30).stdout)
    if not info.get('streams'):
        raise ValueError('No audio stream detected')
    return info


def loudness(path: Path):
    p = subprocess.run(['ffmpeg','-hide_banner','-nostdin','-i',str(path),
        '-af','loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json', '-f','null','-'],
        capture_output=True, text=True, timeout=120, check=False)
    if p.returncode:
        return {'unavailable': 'Unable to measure loudness'}
    match = re.search(r'\{\s*"input_i".*?\}', p.stderr, re.S)
    if not match:
        return {'unavailable': 'No loudness data emitted'}
    j = json.loads(match.group())
    return {key: j.get(key) for key in ('input_i','input_tp','input_lra','input_thresh')}


def visualize(src: Path, dest: Path, mode: str):
    filtergraph = ('showspectrumpic=s=1100x380:legend=disabled:scale=log' if mode == 'spectrum'
                   else 'showwavespic=s=1100x180:colors=0x49dc96')
    try:
        run(['ffmpeg','-hide_banner','-nostdin','-y','-i',str(src), '-filter_complex',filtergraph,
             '-frames:v','1',str(dest)], timeout=90)
        return True
    except Exception:
        return False


def process(job_dir: Path, original: Path, preset: str, output_format: str, do_normalize: bool):
    before = probe(original)
    if preset not in ('transparent', 'gentle', 'vocal'):
        raise ValueError('Invalid preset')
    if output_format not in ('wav', 'flac', 'mp3'):
        raise ValueError('Invalid output format')
    filters = {
        'transparent': [],
        'gentle': ['highpass=f=25', 'equalizer=f=270:t=q:w=1.0:g=-1.2',
                   'equalizer=f=3500:t=q:w=0.8:g=0.8', 'acompressor=threshold=-18dB:ratio=1.45:attack=20:release=180:makeup=1'],
        'vocal': ['highpass=f=35', 'equalizer=f=320:t=q:w=1.1:g=-1.8',
                  'equalizer=f=4500:t=q:w=0.9:g=1.0', 'acompressor=threshold=-20dB:ratio=1.7:attack=15:release=200:makeup=1']
    }[preset]
    if do_normalize:
        filters.append('loudnorm=I=-16:TP=-1.5:LRA=11')
    else:
        filters.append('alimiter=limit=0.94')
    processed = job_dir / f'processed.{output_format}'
    command = ['ffmpeg','-hide_banner','-nostdin','-y','-i',str(original),'-map','0:a:0',
               '-map_metadata','0','-map_chapters','0', '-af', ','.join(filters)]
    if output_format == 'wav':
        command += ['-c:a','pcm_s24le']
    elif output_format == 'flac':
        command += ['-c:a','flac','-compression_level','5']
    else:
        command += ['-c:a','libmp3lame','-b:a','320k','-id3v2_version','3']
    command += [str(processed)]
    run(command)
    after = probe(processed)
    report = {
        'job_id': job_dir.name, 'preset': preset, 'format': output_format,
        'loudness_normalization': do_normalize,
        'original': {'probe': before, 'loudness': loudness(original)},
        'processed': {'probe': after, 'loudness': loudness(processed)},
        'disclaimer': ('These measurements do not identify AI generation or verify watermark removal. '
                       'C2PA/content credentials and embedded metadata may not survive transcoding; '
                       'do not misrepresent the origin or ownership of music.')
    }
    (job_dir / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    visualize(original, job_dir / 'original-spectrum.png', 'spectrum')
    visualize(processed, job_dir / 'processed-spectrum.png', 'spectrum')
    visualize(original, job_dir / 'original-waveform.png', 'waveform')
    visualize(processed, job_dir / 'processed-waveform.png', 'waveform')
    return report


@app.get('/')
def home():
    return FileResponse(Path(__file__).parent / 'static' / 'index.html')


@app.get('/api/health')
def health():
    return {'ok': True, 'max_upload_mb': MAX_BYTES // (1024 * 1024)}


@app.post('/api/process')
async def upload_and_process(
    file: Annotated[UploadFile, File()],
    preset: Annotated[str, Form()] = 'gentle',
    output_format: Annotated[str, Form()] = 'flac',
    normalize: Annotated[bool, Form()] = True
):
    ext = Path(file.filename or '').suffix.lower()
    if ext not in ALLOWED:
        raise HTTPException(400, 'Unsupported audio extension')
    if preset not in ('transparent','gentle','vocal') or output_format not in ('wav','flac','mp3'):
        raise HTTPException(400, 'Invalid processing options')
    job_id = uuid.uuid4().hex
    folder = BASE / job_id
    folder.mkdir(mode=0o700)
    source = folder / f'original{ext}'
    size = 0
    try:
        with source.open('wb') as dest:
            while part := await file.read(1024 * 1024):
                size += len(part)
                if size > MAX_BYTES:
                    raise HTTPException(413, f'Maximum upload: {MAX_BYTES // (1024 * 1024)} MB')
                dest.write(part)
        if not size:
            raise HTTPException(400, 'Empty file')
        report = await asyncio.to_thread(process, folder, source, preset, output_format, normalize)
        return report
    except HTTPException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    except (ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(422, str(error)[:900])
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(500, 'Unexpected processing error')
    finally:
        await file.close()


@app.get('/api/jobs/{job_id}/{asset}')
def fetch_asset(job_id: str, asset: str):
    if not re.fullmatch(r'[a-f0-9]{32}', job_id):
        raise HTTPException(404)
    files = { 'report.json', 'original-spectrum.png', 'processed-spectrum.png',
              'original-waveform.png', 'processed-waveform.png' }
    files.update(f'original{x}' for x in ALLOWED)
    files.update(f'processed.{x}' for x in ('wav','flac','mp3'))
    if asset not in files:
        raise HTTPException(404)
    path = BASE / job_id / asset
    if not path.is_file():
        raise HTTPException(404)
    media_type = 'application/json' if asset.endswith('.json') else None
    return FileResponse(path, media_type=media_type, filename=asset if asset.startswith('processed.') or asset.endswith('.json') else None)
