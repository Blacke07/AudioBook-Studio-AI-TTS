"""Video from existing chapter audio; no AI services or changes to the source WAV."""
import argparse
from bisect import bisect_right
import colorsys
from dataclasses import asdict, dataclass
from functools import lru_cache
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
from threading import Lock
import shutil
import subprocess
import time
import project

from PIL import Image, ImageColor, ImageDraw, ImageFont
import soundfile as sf

from conversion import speakable
from dialogue import NARRATOR, PAUSE, SIMPLE_TAG_RE, UNASSIGNED
from project import title_of

RENDER_VERSION = 3
PALETTE = (14, 200, 330, 150, 42, 265, 95, 185, 300, 60, 230, 0)
BG = '#161311'
INK = '#f1e8dd'
MUTED = '#a5978a'
WARN = '#e0a64a'
ACCENT = '#e27a4b'
FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def color_for(name):
    """Exact web/app.js hash, including JS's first UTF-16 unit per code point."""
    if name == NARRATOR:
        return 'var(--muted)'
    if name == UNASSIGNED:
        return 'var(--warn)'
    hashed = 0
    for char in name:
        code = int.from_bytes(char.encode('utf-16-le')[:2], 'little')
        hashed = (hashed * 31 + code) & 0xffffffff
    return f'hsl({PALETTE[hashed % len(PALETTE)]} 58% 50%)'


def speaker_rgb(name):
    color = color_for(name)
    if color.startswith('var('):
        return ImageColor.getrgb(MUTED if name == NARRATOR else WARN)
    hue = PALETTE[0] if not name else int(color.split('(')[1].split()[0])
    return tuple(round(value * 255) for value in colorsys.hls_to_rgb(hue / 360, .5, .58))


def label_rgb(name):
    """Keep the speaker's hue, but lighten text labels for the dark video background."""
    color = color_for(name)
    if color.startswith('var('):
        return ImageColor.getrgb(MUTED if name == NARRATOR else WARN)
    hue = int(color.split('(')[1].split()[0])
    return tuple(round(value * 255) for value in colorsys.hls_to_rgb(hue / 360, .72, .58))


@dataclass(frozen=True)
class VideoSettings:
    width: int = 1920
    height: int = 1080
    before: int = 2
    after: int = 3
    show_omitted: bool = True
    progress_bar: bool = True
    fps: int = 30
    enabled: bool = False
    footer: str = ''
    codec: str = 'h264'

    def __post_init__(self):
        if not isinstance(self.codec, str) or self.codec not in ('h264', 'h265', 'av1'):
            raise ValueError('Video codec must be h264, h265 or av1.')
        if any(type(value) is not int for value in (self.width, self.height, self.before, self.after, self.fps)):
            raise ValueError('Video dimensions and context counts must be whole numbers.')
        if any(type(value) is not bool for value in (self.show_omitted, self.progress_bar, self.enabled)):
            raise ValueError('Video switches must be true or false.')
        if not isinstance(self.footer, str) or len(self.footer) > 200 or any(ord(c) < 32 for c in self.footer):
            raise ValueError('Video footer must be one line of at most 200 characters.')
        if (self.width, self.height) not in ((1920, 1080), (1280, 720)):
            raise ValueError('Unsupported video resolution.')
        if not 0 <= self.before <= 4 or not 0 <= self.after <= 4 or self.fps != 30:
            raise ValueError('Context must contain 0–4 passages; video uses 30 fps.')

    @classmethod
    def from_dict(cls, values):
        if not isinstance(values, dict) or set(values) - cls.__dataclass_fields__.keys():
            raise ValueError('Invalid video settings.')
        return cls(**values)

    def render_options(self):
        """Automation changes when video runs, not its pixels or measured rendering cost."""
        values = asdict(self)
        del values['enabled']
        # Preserve keys and timing records created before the codec selector existed.
        if self.codec == 'h264':
            del values['codec']
        return values


@dataclass(frozen=True)
class Entry:
    role: str
    text: str
    line: int
    start: float | None
    seconds: float = 0
    omitted: bool = False


class Timeline:
    def __init__(self, script, meta, duration):
        self.duration = duration
        rows = script['rows']
        passages = meta['passages']
        if not passages or not math.isfinite(duration) or duration <= 0:
            raise ValueError('The chapter has no valid audio timing.')
        spoken = {passage['line'] for passage in passages}
        omitted = {index: row for index, row in enumerate(rows)
                   if index not in spoken and row[0] == NARRATOR and SIMPLE_TAG_RE.fullmatch(str(row[1]))}
        self.entries = []
        last_end = 0
        for passage in passages:
            start, seconds = float(passage['start']), float(passage['seconds'])
            line = passage['line']
            if (not math.isfinite(start) or not math.isfinite(seconds) or seconds <= 0 or start < 0
                    or start < last_end - .003 or start + seconds > duration + .02
                    or not isinstance(line, int) or not -1 <= line < len(rows)):
                raise ValueError('Passage timing is invalid or does not match the audio.')
            if line >= 0 and rows[line][0] != passage['role']:
                raise ValueError('The script speakers no longer match the audio. Audio will not be regenerated.')
            for index in sorted(index for index in omitted if index < line):
                row = omitted.pop(index)
                self.entries.append(Entry(row[0], speakable(row[1]), index, None, omitted=True))
            self.entries.append(Entry(passage['role'], speakable(passage['text']), line, start, seconds))
            last_end = start + seconds
        for index, row in sorted(omitted.items()):
            self.entries.append(Entry(row[0], speakable(row[1]), index, None, omitted=True))
        self.spoken = [index for index, entry in enumerate(self.entries) if entry.start is not None]
        self.starts = [self.entries[index].start for index in self.spoken]

    def current(self, moment):
        """Hold the previous passage in gaps and at the end; never highlight omitted tags."""
        return self.spoken[max(0, bisect_right(self.starts, moment) - 1)]


def load_chapter(folder):
    folder = Path(folder)
    audio = folder / 'chapter.wav'
    if not audio.is_file():
        raise ValueError('The chapter has no generated audio. Video cannot be created.')
    script = json.loads((folder / 'script.json').read_text(encoding='utf-8'))
    meta = json.loads((folder / 'audio.json').read_text(encoding='utf-8'))
    duration = sf.info(audio).duration
    if abs(float(meta['seconds']) - duration) > .03:
        raise ValueError('The metadata duration does not match the audio file.')
    return Timeline(script, meta, duration), audio


@lru_cache(maxsize=128)
def _audio_hash(path, size, modified, changed, inode):
    """Avoid rereading hours of unchanged WAV data at every GUI progress poll."""
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.digest()


def cache_key(audio, script, meta, settings, *, volume, title):
    audio = Path(audio).resolve()
    stat = audio.stat()
    digest = hashlib.sha256(_audio_hash(str(audio), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino))
    digest.update(json.dumps([RENDER_VERSION, script, meta, settings.render_options(), volume, title],
                             sort_keys=True, ensure_ascii=False).encode('utf-8'))
    from character_registry import labels
    used = {row[0] for row in script.get('rows', [])}
    video_labels = {name:label for name,label in labels().items() if name in used}
    if video_labels:
        digest.update(json.dumps(video_labels, sort_keys=True, ensure_ascii=False).encode('utf-8'))
    return digest.hexdigest()


def wrap_text(text, font, width):
    """Pixel-measured wrapping; split even a single word wider than the text column."""
    lines = []
    line = ''
    for word in text.split():
        candidate = f'{line} {word}' if line else word
        if font.getlength(candidate) <= width:
            line = candidate
            continue
        if line:
            lines.append(line)
            line = ''
        for char in word:
            if font.getlength(line + char) > width and line:
                lines.append(line)
                line = ''
            line += char
    if line:
        lines.append(line)
    return lines or ['']


def ease(value):
    value = max(0, min(1, value))
    return value * value * (3 - 2 * value)


def ellipsize(text, font, width):
    if font.getlength(text) <= width:
        return text
    while text and font.getlength(text.rstrip() + '…') > width:
        text = text[:-1]
    return text.rstrip() + '…'


class Renderer:
    """A readable chapter canvas with contextual previews and an expanding active row."""
    def __init__(self, timeline, volume, title, settings=VideoSettings()):
        self.timeline, self.settings = timeline, settings
        self.volume, self.title = volume, title
        self.scale = settings.width / 1920
        fonts = Path('C:/Windows/Fonts')
        self.text_font = ImageFont.truetype(str(fonts / 'segoeui.ttf'), 40)
        self.context_font = ImageFont.truetype(str(fonts / 'segoeui.ttf'), 34)
        self.name_font = ImageFont.truetype(str(fonts / 'segoeuib.ttf'), 26)
        self.title_font = ImageFont.truetype(str(fonts / 'georgia.ttf'), 35)
        self.small_font = ImageFont.truetype(str(fonts / 'segoeui.ttf'), 23)
        self.text_width = 1260
        self.line_height = 54
        self.entries = [entry for entry in timeline.entries if settings.show_omitted or not entry.omitted]
        self.original_indices = [index for index, entry in enumerate(timeline.entries)
                                 if settings.show_omitted or not entry.omitted]
        self.index_map = {original: index for index, original in enumerate(self.original_indices)}
        self.lines = [wrap_text(entry.text, self.text_font, self.text_width) for entry in self.entries]
        from character_registry import labels
        display = labels()
        self.names = [wrap_text(display.get(entry.role, entry.role), self.name_font, 270) for entry in self.entries]
        name_heights = [20 + (len(lines) - 1) * 34 + max(self.name_font.getbbox(line)[3] for line in lines) + 10
                        for lines in self.names]
        self.active_heights = [max(116, name_height, min(260, len(lines) * self.line_height + 44))
                               for lines, name_height in zip(self.lines, name_heights)]
        self.context_heights = [max(96 if len(lines) > 1 else 66, name_height)
                                for lines, name_height in zip(self.lines, name_heights)]
        # Bound image storage to this renderer; completed chapters are not retained by a shared cache.
        self.text_image = lru_cache(maxsize=16)(self._text_image)
        self.card = lru_cache(maxsize=64)(self._card)
        self.scaled_text = lru_cache(maxsize=32)(self._scaled_text)
        self.anchor = 525
        self.base = Image.new('RGB', (1920, 1080), BG)
        draw = ImageDraw.Draw(self.base)
        draw.text((90, 40), ellipsize(volume, self.title_font, 1560), font=self.title_font, fill=INK)
        draw.text((92, 94), ellipsize(title, self.small_font, 1740), font=self.small_font, fill=MUTED)
        draw.line((90, 142, 1830, 142), fill='#38312b', width=1)
        if settings.footer:
            draw.text((90, 1010), ellipsize(settings.footer, self.small_font, 1500),
                      font=self.small_font, fill=MUTED)

    def layout(self, active):
        positions = {active: (self.anchor - self.active_heights[active] / 2, self.active_heights[active])}
        edge = positions[active][0]
        for index in range(active - 1, -1, -1):
            height = self.context_heights[index]
            edge -= height + 12
            positions[index] = edge, height
        edge = sum(positions[active]) + 12
        for index in range(active + 1, len(self.entries)):
            height = self.context_heights[index]
            positions[index] = edge, height
            edge += height + 12
        return positions

    def active_at(self, moment):
        return self.index_map[self.timeline.current(moment)]

    def scroll_offset(self, index, moment):
        entry = self.entries[index]
        viewport = self.active_heights[index] - 44
        overflow = max(0, len(self.lines[index]) * self.line_height - viewport)
        if entry.start is None or not overflow:
            return 0
        progress = (moment - entry.start - .6) / max(.2, entry.seconds - 1.2)
        return overflow * max(0, min(1, progress))

    def animated(self, moment):
        original = self.timeline.current(moment)
        position = self.timeline.spoken.index(original)
        entry = self.timeline.entries[original]
        index = self.index_map[original]
        return ((position > 0 and 0 <= moment - entry.start < .35)
                or (self.scroll_offset(index, moment) > 0
                    and moment < entry.start + entry.seconds - .6))

    def _text_image(self, index):
        image = Image.new('L', (self.text_width, max(self.active_heights[index] - 44,
                                                  len(self.lines[index]) * self.line_height)), 0)
        draw = ImageDraw.Draw(image)
        for n, line in enumerate(self.lines[index]):
            draw.text((0, n * self.line_height), line,
                      font=self.title_font if self.entries[index].line == -1 else self.text_font, fill=255)
        return image

    def _scaled_text(self, index, scale):
        image = self.text_image(index)
        if scale == 1:
            return image
        return image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)

    def _labels(self, card, index, opacity=1):
        draw = ImageDraw.Draw(card)
        color = label_rgb(self.entries[index].role)
        if opacity != 1:
            background = tuple(int(BG[i:i+2], 16) for i in (1, 3, 5))
            color = tuple(round(a + (b - a) * opacity) for a, b in zip(background, color))
        for n, name_line in enumerate(self.names[index]):
            draw.text((48, 20 + n * 34), name_line, font=self.name_font, fill=color)

    def _card(self, index, height, weight, opacity, name_opacity):
        entry = self.entries[index]
        card = Image.new('RGB', (1740, max(1, height)), BG)
        draw = ImageDraw.Draw(card)
        background = ImageColor.getrgb(BG)
        mix = lambda color, amount: tuple(round(a + (b - a) * amount) for a, b in zip(background, color))
        if weight > 0:
            draw.rounded_rectangle((0, 0, 1739, height - 1), radius=18,
                                   fill=mix(ImageColor.getrgb('#3d2a20'), weight),
                                   outline=mix(ImageColor.getrgb('#62402e'), weight))
        role_color = speaker_rgb(entry.role)
        draw.ellipse((24, 30, 34, 40), fill=mix(role_color, opacity + (1 - opacity) * weight))
        self._labels(card, index, name_opacity + (1 - name_opacity) * weight)
        if entry.role not in (NARRATOR, PAUSE):
            draw.rounded_rectangle((325, 23, 329, height - 23), radius=2,
                                   fill=mix(role_color, opacity + (1 - opacity) * weight))
        return card

    def styled_card(self, index, height, weight, moment, opacity=1, name_opacity=1):
        """One text mask: interpolate its size and style without overlapping two sets of glyphs."""
        card = self.card(index, height, weight, opacity, name_opacity).copy()
        scale = self.context_font.size / self.text_font.size
        scale += (1 - scale) * weight
        top = round(4 + 15 * weight)
        viewport = max(1, height - round(8 + 36 * weight))
        overflow = max(0, len(self.lines[index]) * self.line_height * scale - viewport)
        entry = self.entries[index]
        progress = 0 if entry.start is None else max(0, min(1, (moment - entry.start - .6) / max(.2, entry.seconds - 1.2)))
        offset = overflow * progress
        visible = self.scaled_text(index, scale).crop((0, round(offset), self.text_width, round(offset) + viewport))
        for step in range(16):
            for edge, strength in ((step, min(1, offset / 16)),
                                   (visible.height - 1 - step, min(1, (overflow - offset) / 16))):
                if strength > 0:
                    band = visible.crop((0, edge, visible.width, edge + 1))
                    visible.paste(Image.blend(band, Image.new('L', band.size, 0),
                                              (1 - step / 16) * .9 * strength * weight), (0, edge))
        background = ImageColor.getrgb(BG)
        ink = ImageColor.getrgb(INK)
        strength = opacity + (1 - opacity) * weight
        color = tuple(round(a + (b - a) * strength) for a, b in zip(background, ink))
        card.paste(color, (350, top, 350 + visible.width, top + visible.height), visible)
        if entry.omitted:
            draw = ImageDraw.Draw(card)
            for n, line in enumerate(self.lines[index]):
                line_y = top + round((n * self.line_height + 29) * scale - offset)
                if top <= line_y < top + viewport:
                    draw.line((350, line_y, 350 + self.text_font.getlength(line) * scale, line_y), fill=color)
        return card

    def frame(self, moment):
        current = self.active_at(moment)
        current_entry = self.entries[current]
        original = self.original_indices[current]
        spoken_position = self.timeline.spoken.index(original)
        previous = self.index_map[self.timeline.spoken[max(0, spoken_position - 1)]]
        blend = ease((moment - current_entry.start) / .35) if spoken_position else 1
        new_layout, old_layout = self.layout(current), self.layout(previous)
        canvas = self.base.copy()
        content = Image.new('RGB', (1920, 810), BG)
        low = max(0, min(current, previous if blend < 1 else current) - self.settings.before)
        high = min(len(self.entries), max(current, previous if blend < 1 else current) + self.settings.after + 1)
        for index in range(low, high):
            y, height = new_layout[index]
            if blend < 1:
                old_y, old_height = old_layout[index]
                y, height = old_y + (y - old_y) * blend, old_height + (height - old_height) * blend
            y = round(y - 166)
            height = round(height)
            if y + height <= 0 or y >= 810:
                continue
            old_distance, new_distance = abs(index - previous), abs(index - current)
            context_opacity = lambda distance: (.25 if self.entries[index].omitted
                                               else {1: .64, 2: .40, 3: .24, 4: .15}.get(distance, .1))
            label_opacity = lambda distance: (.35 if self.entries[index].omitted
                                             else {1: .9, 2: .75, 3: .65, 4: .55}.get(distance, .5))
            opacity = context_opacity(old_distance) * (1 - blend) + context_opacity(new_distance) * blend
            name_opacity = label_opacity(old_distance) * (1 - blend) + label_opacity(new_distance) * blend
            active_weight = ((1 - blend) if index == previous else 0) + (blend if index == current else 0)
            card = self.styled_card(index, height, active_weight, moment, opacity, name_opacity)
            old_visible = previous - self.settings.before <= index <= previous + self.settings.after
            new_visible = current - self.settings.before <= index <= current + self.settings.after
            presence = (1 - blend) * old_visible + blend * new_visible
            if presence < 1:
                card = Image.blend(Image.new('RGB', card.size, BG), card, presence)
            content.paste(card, (90, y))
        # Fade at the viewport edges, without changing the active row's readability.
        for y in range(30):
            alpha = round(255 * (1 - y / 30))
            for edge in (y, 809 - y):
                band = content.crop((0, edge, 1920, edge + 1))
                content.paste(Image.blend(band, Image.new('RGB', band.size, BG), alpha / 255), (0, edge))
        canvas.paste(content, (0, 166))
        draw = ImageDraw.Draw(canvas)
        draw.text((1660, 1010), f'{int(moment)//60:02d}:{int(moment)%60:02d} / '
                  f'{int(self.timeline.duration)//60:02d}:{int(self.timeline.duration)%60:02d}', font=self.small_font, fill=MUTED)
        if self.settings.progress_bar:
            draw.line((90, 994, 1830, 994), fill='#38312b', width=3)
            draw.line((90, 994, 90 + 1740 * min(1, moment / self.timeline.duration), 994), fill=ACCENT, width=3)
        if self.scale != 1:
            canvas = canvas.resize((self.settings.width, self.settings.height), Image.Resampling.LANCZOS)
        return canvas


class VideoCancelled(Exception):
    """A requested stop; completed chapter files are kept."""


def run_ffmpeg(arguments, should_stop=None, progress=None, *, timeout=None):
    bundled = Path(__file__).resolve().parent / 'tools/ffmpeg/ffmpeg.exe'
    executable = str(bundled) if bundled.is_file() else shutil.which('ffmpeg')
    if not executable:
        raise RuntimeError('FFmpeg is not available.')
    command = [executable, '-hide_banner', '-loglevel', 'error', '-nostdin', *arguments]
    if should_stop is None:
        return subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                              errors='replace', creationflags=FLAGS, timeout=timeout)
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               encoding='utf-8', errors='replace', creationflags=FLAGS)
    try:
        while True:
            if should_stop():
                raise VideoCancelled('Video stopped; completed chapters are kept.')
            try:
                stdout, stderr = process.communicate(timeout=.2)
                return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
            except subprocess.TimeoutExpired:
                if progress:
                    progress()
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()


CODECS = {'h264': ('H.264', 'h264_nvenc'), 'h265': ('H.265 (HEVC)', 'hevc_nvenc'),
          'av1': ('AV1', 'av1_nvenc')}
_probe_lock = Lock()


@lru_cache(maxsize=3)
def _probe_codec(codec):
    label, encoder = CODECS[codec]
    try:
        result = run_ffmpeg(['-f', 'lavfi', '-i', 'color=s=1920x1080:r=30', '-frames:v', '3',
                             *encoding_args(encoder), '-pix_fmt', 'yuv420p', '-f', 'null', '-'], timeout=15)
        if result.returncode == 0:
            return {'available': True, 'encoder': encoder, 'reason': 'NVIDIA NVENC'}
        reason = 'NVENC could not encode on this computer. Check GPU, driver and FFmpeg support.'
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        reason = 'FFmpeg or NVENC is unavailable, or its encoding check timed out.'
    if codec == 'h264':
        # H.264 retains its established CPU path, but verify that it works too.
        try:
            result = run_ffmpeg(['-f', 'lavfi', '-i', 'color=s=1920x1080:r=30', '-frames:v', '3',
                                 *encoding_args('libx264'), '-pix_fmt', 'yuv420p', '-f', 'null', '-'], timeout=15)
            if result.returncode == 0:
                return {'available': True, 'encoder': 'libx264', 'reason': 'CPU (libx264); NVENC unavailable'}
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            pass  # Report an unavailable codec; never claim a successful check.
    return {'available': False, 'encoder': None, 'reason': f'{label}: {reason}'}


def codec_capabilities():
    """Session-local real checks. The API runs these in a thread, outside the UI event loop."""
    with _probe_lock:
        return {codec: dict(_probe_codec(codec)) for codec in CODECS}


def choose_encoder(codec='h264'):
    if codec not in CODECS:
        raise ValueError('Unsupported video codec.')
    with _probe_lock:
        capability = _probe_codec(codec)
    if not capability['available']:
        raise RuntimeError(capability['reason'])
    return capability['encoder']


def encoding_args(encoder):
    if encoder in ('h264_nvenc', 'hevc_nvenc', 'av1_nvenc'):
        args = ['-c:v', encoder, '-preset', 'p4', '-rc', 'vbr', '-cq', '18', '-b:v', '0']
        return args + (['-tag:v', 'hvc1'] if encoder == 'hevc_nvenc' else [])
    if encoder == 'libx264':
        return ['-c:v', encoder, '-preset', 'fast', '-crf', '18']
    raise ValueError('Unsupported video encoder.')


def frame_spans(renderer, start, seconds, should_stop=lambda: False):
    """Frame-number holds, split only for movement or the once-per-second clock."""
    fps = renderer.settings.fps
    total = math.ceil(seconds * fps)
    first = 0
    for frame in range(1, total):
        if should_stop():
            raise VideoCancelled('Video stopped.')
        moment, before = start + frame / fps, start + (frame - 1) / fps
        if (renderer.timeline.current(moment) != renderer.timeline.current(before)
                or renderer.animated(moment) or renderer.animated(before)
                or int(moment) != int(before)):
            yield first, frame
            first = frame
    yield first, total


def render_clip(renderer, audio, target, start=0, seconds=None, encoder=None, *, temp_root=None,
                should_stop=lambda: False, progress=lambda fraction, message: None):
    """Sparse PNG keyframes, transitions at 30 fps, and AAC from the untouched source WAV."""
    target = Path(target).resolve()
    if target.exists():
        raise FileExistsError(f'The output already exists: {target}')
    duration = renderer.timeline.duration
    seconds = duration - start if seconds is None else seconds
    if start < 0 or seconds <= 0 or start + seconds > duration + .001:
        raise ValueError('The video interval exceeds the existing audio.')
    began = time.perf_counter()
    fps = renderer.settings.fps
    spans = list(frame_spans(renderer, start, seconds, should_stop))
    if should_stop():
        raise VideoCancelled('Video stopped.')
    # Sample actual PNG sizes, rather than assuming a compression ratio for every book.
    sizes = []
    for index in sorted({0, len(spans)//2, len(spans)-1}):
        sample = BytesIO()
        renderer.frame(start + spans[index][0]/fps).save(sample, format='PNG', compress_level=1)
        sizes.append(sample.tell())
    temporary_root = Path(temp_root) if temp_root else target.parent / '.video-temp'
    from layout import check_path_length
    check_path_length(target)
    check_path_length(temporary_root/'render-00000000/frame-000000.png')
    frames_bytes = math.ceil(sum(sizes)/len(sizes) * len(spans) * 2)
    output_bytes = max(64*1024**2, math.ceil(seconds * 2*1024**2))
    from video_jobs import check_space, temporary_frames, publish_file
    check_space(temporary_root, frames_bytes + output_bytes)
    check_space(target.parent, output_bytes)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoder = encoder or choose_encoder(renderer.settings.codec)
    progress(0, f'Video encoder: {encoder}')
    count = 0
    with temporary_frames(temporary_root) as temporary:
        folder = Path(temporary)
        listing = ['ffconcat version 1.0']
        # The clock label and optional progress bar update once a second on static holds.
        # Render all intermediate frames only during movement, including long-passage scrolling.
        for first, end in spans:
            if should_stop():
                raise VideoCancelled('Video stopped; completed chapters are kept.')
            name = f'frame-{count:06d}.png'
            renderer.frame(start + first / fps).save(folder / name, compress_level=1)
            listing += [f"file '{name}'", 'option framerate 30', f'duration {(end-first)/fps:.9f}']
            count += 1
            progress(.6 * count/len(spans), 'Drawing video frames')
        listing += [f"file 'frame-{count-1:06d}.png'", 'option framerate 30']
        concat = folder / 'frames.txt'
        concat.write_text('\n'.join(listing) + '\n', encoding='utf-8')
        partial = folder / 'video.mp4'
        progress_file = folder / 'encoding.txt'

        def encoding_progress():
            if progress_file.exists():
                lines = progress_file.read_text(encoding='utf-8').splitlines()
                times = [int(line.split('=')[1]) for line in lines if line.startswith('out_time_us=')
                         and line.split('=')[1].lstrip('-').isdigit()]
                if times:
                    progress(.6 + .39 * min(1, max(times)/(seconds*1e6)), 'Encoding MP4')

        result = run_ffmpeg(['-y', '-progress', str(progress_file), '-f', 'concat', '-safe', '0', '-i', str(concat),
                             '-ss', str(start), '-i', str(Path(audio).resolve()),
                             '-map', '0:v:0', '-map', '1:a:0', '-t', f'{seconds:.9f}',
                             '-fps_mode', 'cfr', *encoding_args(encoder),
                             '-vf', (f'fps={fps},scale=in_range=full:out_color_matrix=bt709:out_range=tv,format=yuv420p,'
                                     'setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=limited'),
                             '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv',
                             '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k',
                             '-movflags', '+faststart', str(partial)], should_stop, encoding_progress)
        if result.returncode:
            raise RuntimeError(f'{CODECS[renderer.settings.codec][0]} video encoding failed ({encoder}): ' + result.stderr[-1600:])
        if should_stop():
            raise VideoCancelled('Video stopped; completed chapters are kept.')
        if target.exists():
            raise FileExistsError(f'The output already exists: {target}')
        publish_file(partial, target, should_stop)
        progress(1, 'Video ready')
    return {'file': str(target), 'encoder': encoder, 'render_seconds': round(time.perf_counter() - began, 3),
            'audio_start': start, 'duration': seconds, 'keyframes': count, 'bytes': target.stat().st_size,
            'audio': 'AAC re-encoded from the existing WAV; source WAV unchanged'}



def main():
    parser = argparse.ArgumentParser(description='Render an optional video from existing chapter audio.')
    parser.add_argument('chapter', type=Path, help='Chapter work folder containing script.json, audio.json and chapter.wav')
    parser.add_argument('output', type=Path, help='New MP4 output file; existing files are never overwritten')
    parser.add_argument('--start', type=float, default=0, help='Start time in the chapter audio, in seconds')
    parser.add_argument('--seconds', type=float, help='Clip duration; default: the remainder of the chapter')
    parser.add_argument('--volume', help='Volume title; default: the parent folder name')
    parser.add_argument('--title', help='Chapter title; default: derived from the chapter folder name')
    parser.add_argument('--hide-omitted', action='store_true', help='Hide speech tags omitted from the audio')
    args = parser.parse_args()
    timeline, audio = load_chapter(args.chapter)
    number, title = title_of(args.chapter.name)
    chapter_title = f'Chapter {number} · {title}' if number is not None else title
    renderer = Renderer(timeline, args.volume or args.chapter.parent.name, args.title or chapter_title,
                        VideoSettings(show_omitted=not args.hide_omitted))
    print(json.dumps(render_clip(renderer, audio, args.output, args.start, args.seconds), indent=2))


if __name__ == '__main__':
    main()
