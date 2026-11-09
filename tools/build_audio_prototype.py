"""Create the saved Music-folder practice show; existing shows are kept intact."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from bhs_player.sample_production import build_audio_prototype, NAME


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--music-folder',type=Path,default=Path.home()/'Music')
    parser.add_argument('--name',default=NAME)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]/'Plays'
    folder,created=build_audio_prototype(args.music_folder,root,args.name)
    print(('Created: ' if created else 'Already exists; kept your edits: ')+str(folder.folder))
    print('Saved version:',folder.latest_version().name)
    print('Choose an output in Profile and Routing on first launch; no sound starts automatically.')


if __name__ == '__main__':
    main()
