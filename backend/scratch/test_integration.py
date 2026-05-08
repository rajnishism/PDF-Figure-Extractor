import os
import fitz
import numpy as np
import cv2
from PIL import Image

def test():
    try:
        # Create a dummy PDF
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((100, 100), "Hello World")
        
        # Test fitz processing
        zoom = 2.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        
        # Test numpy integration
        img_data = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        print(f"Shape: {img_data.shape}")
        
        # Test cv2 integration
        if pix.n == 4:
            img_data = cv2.cvtColor(img_data, cv2.COLOR_RGBA2RGB)
        elif pix.n == 3:
             # Already RGB, but let's test a cv2 op
             img_data = cv2.cvtColor(img_data, cv2.COLOR_RGB2BGR)
        
        print("Success!")
        doc.close()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test()
