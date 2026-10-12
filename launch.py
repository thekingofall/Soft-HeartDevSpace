from heartdevspace.server import main

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        import os
        import sys
        if os.name == "nt" and getattr(sys, "frozen", False):
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, str(error), "Soft-HeartDevSpace", 0x10)
        else:
            raise
