import replay_viewer
from multiprocessing import freeze_support

def main():
    app = replay_viewer.ReplayViewer(False)
    app.MainLoop()

if __name__ == "__main__":
    freeze_support()
    main()
