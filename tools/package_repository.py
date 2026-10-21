"""Create the audited public source archive, excluding user data and build artifacts."""
import hashlib
from pathlib import Path
import shutil
import zipfile
from audit_public import audit, source_files

ROOT = Path(__file__).resolve().parents[1]


def main():
    audit(ROOT)
    dist = ROOT / 'dist'
    dist.mkdir(exist_ok=True)
    with zipfile.ZipFile(dist / 'AudioBookStudio-source.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for file in source_files(ROOT):
            archive.write(file, file.relative_to(ROOT).as_posix())
    shutil.copyfile(ROOT / 'build/native-source.zip', dist / 'AudioBookStudio-native-source.zip')
    names = ('AudioBookStudio-Setup-1.0.0.exe', 'AudioBookStudio-source.zip', 'AudioBookStudio-native-source.zip')
    lines = []
    for name in names:
        file = dist / name
        if not file.is_file():
            raise FileNotFoundError(file)
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        lines.append(digest + '  ' + name)
    (dist / 'SHA256SUMS.txt').write_text('\n'.join(lines) + '\n', encoding='ascii')
    for name in ('README.md', 'VERIFICATION.md', 'THIRD_PARTY_NOTICES.md', 'PRIVACY.md', 'LICENSE'):
        shutil.copyfile(ROOT / name, dist / name)
    print('Public source and native source archives created; checksums written to dist/SHA256SUMS.txt.')


if __name__ == '__main__':
    main()
