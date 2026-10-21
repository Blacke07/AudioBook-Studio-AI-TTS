"""Export the exact native source without SDKs, build files or Git data."""
import argparse
from pathlib import Path
import zipfile


def export(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError('The source archive already exists. Refusing to overwrite it.')
    with zipfile.ZipFile(output,'x',zipfile.ZIP_DEFLATED) as archive:
        count=0
        for file in source.rglob('*'):
            relative=file.relative_to(source)
            if any(part in ('.git','build','toolchain','__pycache__') for part in relative.parts):
                continue
            if not file.is_file():
                continue
            if file.suffix.lower() in ('.exe','.dll','.lib','.obj','.pdb','.gguf','.wav','.mp3','.mp4'):
                continue
            archive.write(file,'engine/'+relative.as_posix())
            count+=1
    print('Native source:',output,';',count,'files')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    export(args.source,args.output)
