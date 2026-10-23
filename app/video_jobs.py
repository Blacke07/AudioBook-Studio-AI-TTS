"""Video files, cache records and scratch ownership; never generates or changes chapter audio."""
from contextlib import contextmanager
import ctypes
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory, NamedTemporaryFile

import project
from video import VideoSettings, Renderer, cache_key, load_chapter, render_clip

TEMP_FORMAT = 'audiobook-video-scratch-v1'


def check_space(path, required):
    parent = Path(path).resolve()
    while not parent.exists():
        if parent.parent == parent:
            raise ValueError('The video destination drive is not available.')
        parent = parent.parent
    free = shutil.disk_usage(parent).free
    if free < required:
        raise ValueError(f'Not enough free space for video: need about {required/1024**3:.2f} GB, '
                         f'available {free/1024**3:.2f} GB.')


def publish_file(source, target, should_stop=lambda: False):
    """Atomic destination even when the working folder and export are on different drives."""
    source, target = Path(source), Path(target)
    if should_stop():
        from video import VideoCancelled
        raise VideoCancelled('Video stopped.')
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.stat().st_dev == target.parent.stat().st_dev:
        source.replace(target)
        return
    with NamedTemporaryFile(prefix='video-', suffix='.tmp', dir=target.parent, delete=False) as stream:
        temporary = Path(stream.name)
    try:
        with source.open('rb') as incoming, temporary.open('wb') as outgoing:
            for block in iter(lambda: incoming.read(8*1024**2), b''):
                if should_stop():
                    from video import VideoCancelled
                    raise VideoCancelled('Video stopped.')
                outgoing.write(block)
        if should_stop():
            from video import VideoCancelled
            raise VideoCancelled('Video stopped.')
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def temporary_frames(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='render-', dir=root) as folder:
        project.write_json(Path(folder)/'owner.json', {'format': TEMP_FORMAT, 'pid': os.getpid()})
        yield Path(folder)


def _alive(pid):
    if pid == os.getpid():
        return True
    if os.name == 'nt':
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87  # access denied is not proof a process is dead
        try:
            code = ctypes.c_uint32()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def cleanup_scratch(log):
    _cleanup_root(project.WORK/'video-temp', log)
    for root in project.EXPORT.glob('*/video/.video-temp'):
        if root.resolve().is_relative_to(project.EXPORT.resolve()):
            _cleanup_root(root, log)


def _cleanup_root(root, log):
    if not root.is_dir():
        return
    for folder in root.glob('render-*'):
        # Only direct, owned directories; never follow a link/junction outside the scratch root.
        if (not folder.is_dir() or folder.is_symlink() or folder.is_junction()
                or folder.resolve().parent != root.resolve()):
            continue
        try:
            owner = project._read_json(folder/'owner.json', {})
            if owner.get('format') != TEMP_FORMAT or type(owner.get('pid')) is not int or owner['pid'] <= 0:
                continue
            if _alive(owner['pid']):
                continue
            shutil.rmtree(folder)
            log(f'Removed abandoned video temporary files: {folder.name}')
        except (OSError, ValueError) as error:
            log(f'Could not clean video scratch {folder.name}: {error}')


def video_path(chapter):
    return project.EXPORT/project.safe_name(chapter.volume)/'video'/f'{project.safe_name(chapter.stem)}.mp4'


def chapter_title(chapter):
    return f'Chapter {chapter.number} · {chapter.title}' if chapter.number is not None else chapter.title


def fingerprint(chapter, settings):
    script = chapter.script()
    display = None
    if script:
        from character_registry import resolved_labels
        display = resolved_labels(script.get('rows', []), chapter.volume, chapter.stem,
                                  source_hash=script.get('source_hash'))
    return cache_key(chapter.audio_file, script, project._read_json(chapter.audio_meta, None),
                     VideoSettings.from_dict(settings.get('video', {})),
                     volume=chapter.volume, title=chapter_title(chapter), display=display)


def video_status(chapter, settings, audio_current):
    target = video_path(chapter)
    record = project._read_json(chapter.work/'video.json', {})
    result = {'state': 'none', 'label': 'No video'}
    error = chapter.work/'video-error.txt'
    if error.exists():
        result['error'] = error.read_text(encoding='utf-8')
    if not target.is_file():
        return result
    ready = False
    if audio_current and record and chapter.audio_file.is_file() and chapter.script_file.is_file():
        ready = (record.get('key') == fingerprint(chapter, settings)
                 and record.get('bytes') == target.stat().st_size)
    return {**result, 'state': 'ready' if ready else 'outdated',
            'label': 'Video ready' if ready else 'Video outdated', 'file': str(target),
            'duration': record.get('duration')}


def measurement(settings=None):
    data = project._read_json(project.WORK/'video-timing.json', {})
    if settings is not None:
        recorded = data.get('settings')
        if (not isinstance(recorded, dict) or VideoSettings.from_dict(recorded).render_options()
                != VideoSettings.from_dict(settings.get('video', {})).render_options()):
            return None
    factor = data.get('factor')
    return factor if type(factor) in (int, float) and math.isfinite(factor) and factor > 0 else None


def create_chapter(chapter, settings, should_stop, progress, log):
    if video_status(chapter, settings, True)['state'] == 'ready':
        log(f'Video already current: {chapter.stem}')
        return None
    options = VideoSettings.from_dict(settings.get('video', {}))
    timeline, audio = load_chapter(chapter.work)
    key = fingerprint(chapter, settings)
    script = chapter.script() or {'rows': []}
    from character_registry import resolved_labels
    display = resolved_labels(script.get('rows', []), chapter.volume, chapter.stem,
                              source_hash=script.get('source_hash'))
    renderer = Renderer(timeline, chapter.volume, chapter_title(chapter), options, display=display)
    target = video_path(chapter)
    from video import VideoCancelled
    # Finished output replaces an outdated video only after successful rendering and a fresh input check.
    with temporary_frames(target.parent/'.video-temp') as folder:
        result = render_clip(renderer, audio, folder/'complete.mp4',
                             temp_root=target.parent/'.video-temp', should_stop=should_stop, progress=progress)
        probe_video(result['file'], expected_seconds=timeline.duration)
        if should_stop():
            raise VideoCancelled('Video stopped; completed chapters are kept.')
        if fingerprint(chapter, project.load_settings()) != key:
            raise ValueError('Video inputs changed during rendering. Create the video again.')
        target.parent.mkdir(parents=True, exist_ok=True)
        publish_file(result['file'], target, should_stop)
    result['file'] = target.name
    result['key'] = key
    encoder = result['encoder']
    log(f'Video encoder: {encoder}')
    project.write_json(chapter.work/'video.json', result)
    project.write_json(project.WORK/'video-timing.json', {
        'factor': result['render_seconds']/result['duration'], 'encoder': encoder,
        'settings': options.render_options(), 'measured_audio_seconds': result['duration']})
    (chapter.work/'video-error.txt').unlink(missing_ok=True)
    log(f'Video ready: {chapter.stem} · {result["render_seconds"]:.1f} s for {result["duration"]:.1f} s audio')
    return result


def probe_video(path, expected_seconds=None):
    bundled = Path(__file__).resolve().parent/'tools/ffmpeg/ffprobe.exe'
    executable = str(bundled) if bundled.is_file() else shutil.which('ffprobe')
    if not executable:
        raise RuntimeError('FFprobe is not available.')
    result = subprocess.run([executable, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
                            capture_output=True, text=True, encoding='utf-8', errors='replace',
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise ValueError('Cannot read the video duration: ' + result.stderr[-400:])
    data = json.loads(result.stdout)
    streams = {row['codec_type']: row for row in data['streams']}
    if not {'audio', 'video'} <= streams.keys():
        raise ValueError('The MP4 must contain both video and audio.')
    video_seconds = float(streams['video']['duration'])
    audio_seconds = float(streams['audio']['duration'])
    container_seconds = float(data['format']['duration'])
    durations = (video_seconds, audio_seconds, container_seconds)
    if not all(math.isfinite(value) and value > 0 for value in durations) or abs(video_seconds-audio_seconds) > .08:
        raise ValueError('The video and audio durations do not match.')
    if expected_seconds is not None and any(abs(value-expected_seconds) > .08 for value in durations):
        raise ValueError('The encoded video duration does not match the chapter audio.')
    return container_seconds


def youtube_chapters(volume, stems, settings):
    chapters = project.chapters(volume)
    if stems:
        chapters = [chapter for chapter in chapters if chapter.stem in stems]
    if not chapters:
        raise ValueError('No chapters were selected.')
    import glossary
    import pipeline
    rows = glossary.load()
    lines, offset = [], 0.
    previous = -1
    for chapter in chapters:
        current = pipeline.status(chapter, settings, rows)[0] in ('generated', 'exported')
        if video_status(chapter, settings, current)['state'] != 'ready':
            raise ValueError(f'{chapter.stem}: create an up-to-date video first.')
        second = int(offset)
        if second <= previous:
            raise ValueError('Videos are too short to give distinct whole-second chapter timestamps.')
        previous = second
        minutes, seconds = divmod(second, 60)
        hours, minutes = divmod(minutes, 60)
        timestamp = f'{hours:02d}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes:02d}:{seconds:02d}'
        title = f'Chapter {chapter.number} — {chapter.title}' if chapter.number is not None else chapter.title
        lines.append(f'{timestamp} {title}')
        offset += probe_video(video_path(chapter))
    target = project.EXPORT/project.safe_name(volume)/'video'/'YouTube chapters.txt'
    temporary = target.with_suffix('.tmp')
    temporary.write_text('\n'.join(lines)+'\n', encoding='utf-8')
    temporary.replace(target)
    return target
