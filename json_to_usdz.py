"""Convert a saved SMLib Modeler JSON document to USDZ."""

from json_to_glb import main


if __name__ == "__main__":
    raise SystemExit(main(format="usdz"))
