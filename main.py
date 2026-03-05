from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
import yt_dlp
import os
import glob
import asyncio
import time
import subprocess  # ← Import corrigido (era o causador do erro 500)
import traceback
from pydantic import BaseModel

app = FastAPI(title="ILIMITHI STORYs API")

class LinkRequest(BaseModel):
    url: str

@app.post("/download")
async def download(request: LinkRequest):
    url = request.url.strip()
    print(f"[API] Requisição recebida: {url}")
    
    if not url:
        raise HTTPException(status_code=400, detail="URL vazia")
    
    if not any(site in url.lower() for site in ["instagram.com", "youtube.com", "youtu.be", "tiktok.com", "x.com", "facebook.com"]):
        raise HTTPException(status_code=400, detail="Plataforma não suportada")
    
    try:
        print("[API] Iniciando download_content...")
        file_path, extension = await download_content(url)
        print(f"[API] Arquivo gerado: {file_path} ({extension})")
        
        if not file_path or not os.path.exists(file_path):
            raise Exception("Arquivo não foi gerado após processamento")
        
        print("[API] Enviando arquivo para o cliente")
        response = FileResponse(
            path=file_path,
            filename=os.path.basename(file_path),
            media_type="application/octet-stream"
        )
        
        # Remove arquivo após envio (em background)
        asyncio.create_task(cleanup_file(file_path))
        
        return response
        
    except Exception as e:
        print(f"[API] ERRO 500: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Erro interno: {str(e)}")

async def cleanup_file(file_path: str):
    try:
        await asyncio.sleep(8)
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"[API] Arquivo temporário removido: {file_path}")
    except Exception as e:
        print(f"[API] Erro ao limpar arquivo: {str(e)}")

# ====================== SUA FUNÇÃO DOWNLOAD_CONTENT ======================
async def download_content(url: str):
    start_time = time.time()
    url = url.strip()
    clean_url = url.split('&')[0]
    
    if 'youtube.com/watch' in clean_url and 'v=' not in clean_url:
        raise Exception("Link YouTube incompleto (faltou ?v=ID). Copie completo!")
    
    if 'youtu.be/' in clean_url:
        video_id = clean_url.split('youtu.be/')[-1].split('?')[0]
        clean_url = f"https://www.youtube.com/watch?v={video_id}"
    
    output_template = 'file_%(id)s.%(ext)s'
    
    ydl_opts = {
        'format': 'best',
        'outtmpl': output_template,
        'cookiefile': 'cookies.txt',
        'quiet': False,
        'no_warnings': False,
        'ffmpeg_location': './',
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'referer': 'https://www.instagram.com/',
        'noplaylist': True,
        'ignoreerrors': True,
        'extractor_args': {'youtube': {'player_client': ['tv', 'web', 'android', 'ios']}},
        'nocheckcertificate': True,
        'verbose': True,
        'sleep_interval': 1,
        'max_sleep_interval': 3,
        'retries': 10,
        'fragment_retries': 10,
        'continuedl': True,
        'http_chunk_size': 10485760,
        'force_ipv4': True,
        'geo_bypass': True,
        'external_downloader': 'aria2c',
        'external_downloader_args': [
            '-x', '4',
            '-k', '1M',
            '--min-split-size=1M',
            '--max-connection-per-server=4',
            '--summary-interval=0',
            '--timeout=120',
            '--connect-timeout=30'
        ],
    }
    
    loop = asyncio.get_event_loop()
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = None
        try:
            info = await loop.run_in_executor(None, lambda: ydl.extract_info(clean_url, download=False))
        except Exception as e:
            print(f"[DEBUG] extract_info erro: {str(e)}")
        
        base_name = None
        file_path = None
        extension = None

        download_start = time.time()
        if info is not None and info.get('id'):
            file_id = info['id']
            base_name = f"file_{file_id}"
            ext = info.get('ext', 'mp4')
            filename = f"{base_name}.{ext}"
            if not os.path.exists(filename):
                await loop.run_in_executor(None, lambda: ydl.download([clean_url]))
        else:
            await loop.run_in_executor(None, lambda: ydl.download([clean_url]))
            candidates = glob.glob("file_*.*")
            if candidates:
                latest = max(candidates, key=os.path.getctime)
                base_name = os.path.splitext(latest)[0]
                extension = os.path.splitext(latest)[1].lstrip('.').lower()
                file_path = latest

        download_time = time.time() - download_start
        print(f"[DEBUG] Tempo de download: {download_time:.2f} segundos")

        # Fallback para stories do Instagram
        if "instagram.com" in clean_url and "/stories/" in clean_url:
            file_id = clean_url.rstrip('/').split('/')[-1]
            base_name = f"file_{file_id}"
            cmd = [
                'gallery-dl',
                '--dest', '.',
                '-o', 'directory=[]',
                '-f', f'file_{{media_id}}.{{extension}}',
                '--cookies', 'cookies.txt',
                '--verbose',
                clean_url
            ]
            try:
                result = await loop.run_in_executor(None, lambda: subprocess.run(
                    cmd, check=True, capture_output=True, text=True, timeout=120
                ))
            except subprocess.CalledProcessError as e:
                raise Exception(f"Gallery-dl falhou: {e.stderr.decode() if e.stderr else str(e)}")
            except asyncio.TimeoutError:
                raise Exception("Gallery-dl timeout")
            
            candidates = glob.glob(f"file_{file_id}.*")
            if candidates:
                file_path = candidates[0]
                extension = file_path.split('.')[-1].lower()
            else:
                all_files = glob.glob("file_*.*")
                if all_files:
                    file_path = max(all_files, key=os.path.getctime)
                    extension = file_path.split('.')[-1].lower()

        if not file_path and base_name:
            for e in ['mp4', 'jpg', 'jpeg', 'png', 'webp', 'webm', 'mkv']:
                candidate = f"{base_name}.{e}"
                if os.path.exists(candidate):
                    file_path = candidate
                    extension = e.lower()
                    break

        if file_path and os.path.exists(file_path):
            total_time = time.time() - start_time
            print(f"[DEBUG] Tempo total: {total_time:.2f} segundos")
            return file_path, extension
        else:
            raise Exception("Nenhum arquivo gerado. Verifique logs.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
