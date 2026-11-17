from app.main import main

# The guard matters: the analysis worker is started with multiprocessing "spawn", which
# re-imports this module in the child; without it the child would open a second IDE.
if __name__ == "__main__":
    raise SystemExit(main())
