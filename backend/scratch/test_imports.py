try:
    import fitz
    print("fitz imported")
    import cv2
    print("cv2 imported")
    import numpy as np
    print("numpy imported")
    import re
    print("re imported")
    from PIL import Image
    print("PIL imported")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
