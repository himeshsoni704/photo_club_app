import face_recognition
import cv2
import numpy as np
import os
import warnings
# Suppress the pkg_resources UserWarning, which is not an error in your code
warnings.filterwarnings("ignore", category=UserWarning, module='face_recognition_models')

# --- CONFIGURATION ---
KNOWN_FACES_DIR = "known_faces" # Folder containing images of known people
CAMERA_INDEX = 0               # 0 is usually the built-in webcam

# --- GLOBAL VARIABLES ---
known_face_encodings = []
known_face_names = []

## 🖼️ 1. Load and Encode Known Faces (Training Data)
print("Encoding known faces...")

# Check if the known_faces directory exists
if not os.path.isdir(KNOWN_FACES_DIR):
    print(f"Error: Directory '{KNOWN_FACES_DIR}' not found.")
    print("Please create this folder and add images of the people you want to recognize.")
    exit()

# Loop through all files in the known_faces directory
for filename in os.listdir(KNOWN_FACES_DIR):
    # Process only image files
    if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
        path = os.path.join(KNOWN_FACES_DIR, filename)
        
        # Load image
        image = face_recognition.load_image_file(path)
        
        # Get face encodings
        face_encodings_list = face_recognition.face_encodings(image)
        
        if len(face_encodings_list) > 0:
            encoding = face_encodings_list[0]
            known_face_encodings.append(encoding)
            
            # Use the cleaned-up filename as the person's name
            name = os.path.splitext(filename)[0]
            known_face_names.append(name.replace('_', ' ').title())
            print(f"   Encoded: {name}")
        else:
            print(f"   Warning: No face found in {filename}. Skipping.")

print(f"Finished encoding {len(known_face_names)} known faces.")

if not known_face_encodings:
    print("Error: No valid faces were encoded. Exiting.")
    exit()

# --- REAL-TIME RECOGNITION SETUP ---

# Initialize video capture
video_capture = cv2.VideoCapture(CAMERA_INDEX) 

# Variables for processing frames
face_locations = []
face_encodings = []
process_this_frame = True

print("\nStarting real-time face recognition. Look at the camera.")
print("Press 'q' to exit the video window.")

## 🏃 2. Main Recognition Loop
while True:
    # Grab a single frame of video
    ret, frame = video_capture.read()

    # Skip some frames to improve performance (optional)
    if process_this_frame:
        # Resize frame to 1/4 size for faster processing
        small_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
        # Convert BGR (OpenCV) to RGB (face_recognition)
        rgb_small_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)

        # Find all the faces and face encodings in the current frame
        face_locations = face_recognition.face_locations(rgb_small_frame)
        face_encodings = face_recognition.face_encodings(rgb_small_frame, face_locations)

        face_names = []
        for face_encoding in face_encodings:
            # Compare the face to the known faces
            matches = face_recognition.compare_faces(known_face_encodings, face_encoding)
            name = "Unknown"

            # Find the best match using face distance
            face_distances = face_recognition.face_distance(known_face_encodings, face_encoding)
            best_match_index = np.argmin(face_distances)
            
            # If the best match is below the recognition threshold (a smaller number is a closer match)
            if matches[best_match_index]:
                name = known_face_names[best_match_index]

            face_names.append(name)

    process_this_frame = not process_this_frame # Toggle frame processing for optimization

    # Display the results
    for (top, right, bottom, left), name in zip(face_locations, face_names):
        # Scale locations back up since we processed a small frame
        top *= 4
        right *= 4
        bottom *= 4
        left *= 4

        # Draw box and label
        color = (0, 255, 0) if name != "Unknown" else (0, 0, 255) # Green for known, Red for unknown
        cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
        cv2.rectangle(frame, (left, bottom - 35), (right, bottom), color, cv2.FILLED)
        font = cv2.FONT_HERSHEY_DUPLEX
        cv2.putText(frame, name, (left + 6, bottom - 6), font, 1.0, (255, 255, 255), 1)

    # Display the resulting image
    cv2.imshow('Face Recognition System', frame)

    # Hit 'q' on the keyboard to quit
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

## 🛑 3. Clean Up
video_capture.release()
cv2.destroyAllWindows()