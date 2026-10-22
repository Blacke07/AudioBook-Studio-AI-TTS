"""Prepare audited source archives in build/ and the installer checksum in dist/."""
from pathlib import Path
import zipfile
from audit_public import audit, source_files
from build import SETUP_NAME, sha256

ROOT = Path(__file__).resolve().parents[1]


def main():
    audit(ROOT)
    dist = ROOT / 'dist'
    digest = sha256(dist / SETUP_NAME)
    build = ROOT / 'build'
    build.mkdir(exist_ok=True)
    with zipfile.ZipFile(build / 'AudioBookStudio-source.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for file in source_files(ROOT):
            archive.write(file, file.relative_to(ROOT).as_posix())
    (dist / 'SHA256SUMS.txt').write_text(digest + '  ' + SETUP_NAME + '\n', encoding='ascii')
    print('Source archives: build/AudioBookStudio-source.zip and build/native-source.zip. '
          'Installer checksum: dist/SHA256SUMS.txt.')


if __name__ == '__main__':
    main()
