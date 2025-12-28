# Kokoro TTS RunPod Serverless Worker
# Build: docker build -t your-dockerhub/kokoro-tts:latest .
# Push:  docker push your-dockerhub/kokoro-tts:latest

FROM runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04

WORKDIR /app

# Install Kokoro TTS and dependencies
RUN pip install --no-cache-dir \
    kokoro>=0.3.0 \
    numpy \
    runpod \
    soundfile

# Pre-download the Kokoro model during build to speed up cold starts
RUN python -c "from kokoro import KPipeline; KPipeline(lang_code='a')"

# Copy handler
COPY handler.py /app/handler.py

# Run the serverless handler
CMD ["python", "-u", "/app/handler.py"]
