import math
import ctypes as C
from array import array
from pathlib import Path
import sys
import tempfile
import unittest
import wave
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tweakout_worker import make_audio,read_sound,FaultDisplay,WavePlayer,RATE,AUDIO_SECONDS

class EffectsTests(unittest.TestCase):
    def player_fixture(self,failure=''):
        api=Mock();api.waveOutGetNumDevs.return_value=3
        def open_device(handle,device,*args):
            if device==0xffffffff or failure=='open':return 2
            C.cast(handle,C.POINTER(C.c_void_p)).contents.value=123;return 0
        api.waveOutOpen.side_effect=open_device
        for name in ('waveOutPrepareHeader','waveOutWrite','waveOutReset','waveOutUnprepareHeader','waveOutClose'):getattr(api,name).return_value=0
        if failure in ('prepare','write'):getattr(api,'waveOutPrepareHeader' if failure=='prepare' else 'waveOutWrite').return_value=1
        return WavePlayer(api),api
    def fixture_wav(self,path):
        with wave.open(str(path),'wb') as output:
            output.setnchannels(1);output.setsampwidth(2);output.setframerate(RATE);output.writeframes(b'\0\0'*100)
    def test_native_player_fallback_loops_and_closes_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'test.wav';self.fixture_wav(path);player,api=self.player_fixture()
            self.assertEqual(player.start(path),0);self.assertEqual(api.waveOutOpen.call_count,2)
            self.assertEqual(player.header.flags,12);self.assertEqual(player.header.loops,0xffffffff);self.assertIsNotNone(player.buffer)
            player.close();player.close();api.waveOutReset.assert_called_once();api.waveOutClose.assert_called_once();self.assertIsNone(player.buffer)
    def test_native_player_partial_failures_close_owned_handles(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'test.wav';self.fixture_wav(path)
            for failure in ('open','prepare','write'):
                player,api=self.player_fixture(failure)
                with self.assertRaises(RuntimeError):player.start(path)
                self.assertIsNone(player.buffer)
                self.assertEqual(api.waveOutClose.call_count,0 if failure=='open' else 1)
                self.assertEqual(api.waveOutUnprepareHeader.call_count,1 if failure=='write' else 0)
    def test_failed_native_reset_retains_buffer_until_successful_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'test.wav';self.fixture_wav(path);player,api=self.player_fixture();player.start(path)
            api.waveOutReset.return_value=1
            with self.assertRaises(RuntimeError):player.close()
            self.assertIsNotNone(player.buffer);api.waveOutClose.assert_not_called()
            api.waveOutReset.return_value=0;player.close();self.assertIsNone(player.buffer)
    def test_audio_fallback_is_bounded_audible_and_not_clipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'audio.wav';self.assertEqual(make_audio(path,Path(tmp)),[])
            with wave.open(str(path)) as wav:
                self.assertEqual(wav.getnframes(),RATE*AUDIO_SECONDS);self.assertEqual(wav.getnchannels(),1)
                pcm=array('h');pcm.frombytes(wav.readframes(wav.getnframes()))
            rms=math.sqrt(sum((v/32768)**2 for v in pcm)/len(pcm))
            self.assertGreater(rms,.07);self.assertLessEqual(max(abs(v) for v in pcm),.751*32768)
    def test_pcm_resample_and_unsupported_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'cue.wav'
            with wave.open(str(path),'wb') as wav:
                wav.setnchannels(2);wav.setsampwidth(2);wav.setframerate(44100);wav.writeframes(array('h',[16384,16384]*4410).tobytes())
            cue=read_sound(path);self.assertEqual(len(cue),2205);self.assertEqual(cue[0],.5)
            with wave.open(str(path),'wb') as wav:
                wav.setnchannels(1);wav.setsampwidth(1);wav.setframerate(22050);wav.writeframes(b'\x80'*100)
            with self.assertRaises(ValueError):read_sound(path)
    def test_fault_stages_have_no_countdown_and_keep_effect_identification(self):
        class Canvas:
            def __init__(self):self.text=[]
            def create_text(self,*a,**kw):self.text.append(kw['text'])
            def __getattr__(self,name):return lambda *a,**kw:None
        for elapsed in (0,5,9):
            canvas=Canvas();FaultDisplay(canvas,1600,1000).draw(elapsed)
            content='\n'.join(canvas.text)
            self.assertIn('HomeControl • visual effect',content);self.assertNotIn('countdown',content.lower())
            self.assertNotIn('CPU',content);self.assertNotIn('seconds',content)
        self.assertIn('VIDEO_TDR_FAILURE',content)

if __name__=='__main__':unittest.main()
