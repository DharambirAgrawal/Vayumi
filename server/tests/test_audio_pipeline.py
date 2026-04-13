"""Test audio pipeline."""
import pytest
import struct

from audio.pipeline import AudioPipeline


@pytest.mark.asyncio
async def test_audio_pipeline_init():
    """Test audio pipeline initialization."""
    pipeline = AudioPipeline(sample_rate=16000)
    
    assert pipeline.sample_rate == 16000
    assert pipeline.chunk_duration_ms == 20
    assert pipeline.samples_per_chunk == 320
    assert pipeline.bytes_per_chunk == 640


@pytest.mark.asyncio
async def test_process_audio_chunk():
    """Test processing an audio chunk."""
    pipeline = AudioPipeline(sample_rate=16000)
    session_id = "test_session"
    
    # Create a valid audio chunk (320 samples, 16-bit PCM)
    samples = [0] * 320  # Silence
    chunk = struct.pack(f"{len(samples)}h", *samples)
    
    assert len(chunk) == 640
    
    event = await pipeline.process_chunk(session_id, chunk)
    # Silence should not trigger speech detection
    assert event is None or not event.is_speech


@pytest.mark.asyncio
async def test_vad_speech_detection():
    """Test VAD speech detection."""
    pipeline = AudioPipeline(sample_rate=16000)
    pipeline.vad_threshold = 0.1  # Lower threshold for testing
    session_id = "test_session"
    
    # Create a chunk with some energy (simulating speech)
    samples = [1000] * 320  # Non-zero samples
    chunk = struct.pack(f"{len(samples)}h", *samples)
    
    event = await pipeline.process_chunk(session_id, chunk)
    # This should be detected as speech
    assert event is not None  # State change from silence to speech


@pytest.mark.asyncio
async def test_get_buffered_audio():
    """Test retrieving buffered audio."""
    pipeline = AudioPipeline(sample_rate=16000)
    session_id = "test_session"
    
    # Add chunks
    samples = [100] * 320
    chunk = struct.pack(f"{len(samples)}h", *samples)
    
    await pipeline.process_chunk(session_id, chunk)
    await pipeline.process_chunk(session_id, chunk)
    
    # Get buffered audio
    audio_data = await pipeline.get_buffered_audio(session_id)
    assert audio_data is not None
    assert len(audio_data) == 1280  # 2 chunks
    
    # Buffer should be cleared
    audio_data_2 = await pipeline.get_buffered_audio(session_id)
    assert audio_data_2 is None


@pytest.mark.asyncio
async def test_reset_session():
    """Test resetting a session's buffers."""
    pipeline = AudioPipeline(sample_rate=16000)
    session_id = "test_session"
    
    # Add chunks
    samples = [100] * 320
    chunk = struct.pack(f"{len(samples)}h", *samples)
    
    await pipeline.process_chunk(session_id, chunk)
    
    # Reset
    await pipeline.reset_session(session_id)
    
    # Buffer should be empty
    audio_data = await pipeline.get_buffered_audio(session_id)
    assert audio_data is None


@pytest.mark.asyncio
async def test_rms_calculation():
    """Test RMS energy calculation."""
    pipeline = AudioPipeline()
    
    # Silence should have low RMS
    silent_samples = [0] * 320
    silent_chunk = struct.pack(f"{len(silent_samples)}h", *silent_samples)
    silent_rms = pipeline._calculate_rms(silent_chunk)
    
    # Loud signal should have high RMS
    loud_samples = [10000] * 320
    loud_chunk = struct.pack(f"{len(loud_samples)}h", *loud_samples)
    loud_rms = pipeline._calculate_rms(loud_chunk)
    
    assert silent_rms < loud_rms


@pytest.mark.asyncio
async def test_session_transcript():
    """Test retrieving session transcript."""
    from models import Session, TranscriptionSegment
    
    pipeline = AudioPipeline()
    session = Session()
    
    # Add some segments
    session.transcriptions = [
        TranscriptionSegment(text="Hello", start_ms=0, end_ms=500, confidence=0.95),
        TranscriptionSegment(text="world", start_ms=500, end_ms=1000, confidence=0.93),
    ]
    
    transcript = await pipeline.get_session_transcript(session)
    assert "Hello" in transcript
    assert "world" in transcript


@pytest.mark.asyncio
async def test_process_variable_chunk_sizes_rechunked():
    """Test that arbitrary packet sizes are split into 20ms internal chunks."""
    pipeline = AudioPipeline(sample_rate=16000)
    session_id = "variable_chunk_session"

    # 2730 bytes emulates the browser packet size observed in logs.
    odd_chunk = b"\x01\x00" * (2730 // 2)
    assert len(odd_chunk) == 2730

    await pipeline.process_chunk(session_id, odd_chunk)
    buffered = await pipeline.get_buffered_audio(session_id)

    # Only complete 640-byte frames are emitted to the internal buffer.
    assert buffered is not None
    assert len(buffered) == 2560
