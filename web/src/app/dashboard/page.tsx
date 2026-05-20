"use client";

import { useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';

interface Job {
  id: string;
  status: string;
  created_at: string;
  error?: string;
  download_url?: string;
}

export default function Dashboard() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [uploading, setUploading] = useState(false);
  const router = useRouter();

  const fetchJobs = useCallback(async () => {
    const token = localStorage.getItem('token');
    if (!token) return router.push('/');
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/jobs`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        setJobs(await res.json());
      } else if (res.status === 401) {
        router.push('/');
      }
    } catch (e) {
      console.error(e);
    }
  }, [router]);

  useEffect(() => {
    fetchJobs();
    const interval = setInterval(fetchJobs, 5000);
    return () => clearInterval(interval);
  }, [fetchJobs]);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploading(true);
    const token = localStorage.getItem('token');
    
    try {
      const preRes = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/uploads/presign`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });
      const { upload_url, file_key } = await preRes.json();

      await fetch(upload_url, {
        method: 'PUT',
        body: file,
        headers: { 'Content-Type': 'video/mp4' }
      });

      await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/jobs`, {
        method: 'POST',
        headers: { 
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ input_key: file_key })
      });

      fetchJobs();
    } catch (_) {
      alert('Error subiendo el video');
    }
    setUploading(false);
  };

  const getJobDetail = async (id: string) => {
    const token = localStorage.getItem('token');
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
    const res = await fetch(`${apiUrl}/jobs/${id}`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (res.ok) {
      const data = await res.json();
      if (data.download_url) {
        // download_url is a relative path like "/jobs/{id}/download"
        // Use fetch + blob to download with auth header
        const dlRes = await fetch(`${apiUrl}${data.download_url}`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        if (dlRes.ok) {
          const blob = await dlRes.blob();
          const url = window.URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = `video-${id.slice(0, 8)}.mp4`;
          document.body.appendChild(a);
          a.click();
          window.URL.revokeObjectURL(url);
          a.remove();
        } else {
          alert('Error descargando el video');
        }
      }
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-50 p-8">
      <div className="max-w-6xl mx-auto space-y-8">
        <header className="flex justify-between items-center">
          <h1 className="text-3xl font-bold bg-gradient-to-r from-violet-400 to-fuchsia-400 bg-clip-text text-transparent">
            Dashboard
          </h1>
          <button 
            onClick={() => { localStorage.removeItem('token'); router.push('/'); }}
            className="text-slate-400 hover:text-white transition-colors"
          >
            Cerrar Sesión
          </button>
        </header>

        {/* Upload Zone */}
        <div className="bg-slate-900 border-2 border-dashed border-slate-700 rounded-2xl p-12 text-center transition-colors hover:border-violet-500">
          <input 
            type="file" 
            accept="video/mp4" 
            onChange={handleUpload} 
            className="hidden" 
            id="video-upload" 
            disabled={uploading}
          />
          <label htmlFor="video-upload" className="cursor-pointer space-y-4 block">
            <div className="mx-auto w-16 h-16 bg-slate-800 rounded-full flex items-center justify-center">
              <svg className="w-8 h-8 text-violet-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
              </svg>
            </div>
            <div className="text-lg font-medium">
              {uploading ? 'Subiendo...' : 'Arrastra un video o haz clic aquí'}
            </div>
            <div className="text-sm text-slate-400">Output: 3840x2160 con fondo blur (bypass confirmado)</div>
          </label>
        </div>

        {/* Jobs List */}
        <div className="space-y-4">
          <h2 className="text-xl font-semibold">Tus Videos Procesados</h2>
          {jobs.length === 0 ? (
            <p className="text-slate-500">No hay videos procesados todavía.</p>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {jobs.map(job => (
                <div key={job.id} className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
                  <div className="flex justify-between items-center">
                    <span className={`px-3 py-1 rounded-full text-xs font-medium uppercase tracking-wider ${
                      job.status === 'done' ? 'bg-green-500/10 text-green-400' :
                      job.status === 'failed' ? 'bg-red-500/10 text-red-400' :
                      job.status === 'processing' ? 'bg-blue-500/10 text-blue-400' :
                      'bg-slate-800 text-slate-300'
                    }`}>
                      {job.status}
                    </span>
                    <span className="text-xs text-slate-500">
                      {new Date(job.created_at).toLocaleDateString()}
                    </span>
                  </div>
                  
                  <div className="text-sm font-mono text-slate-400 truncate">
                    ID: {job.id.slice(0, 8)}...
                  </div>

                  {job.status === 'done' && (
                    <button 
                      onClick={() => getJobDetail(job.id)}
                      className="w-full py-2 bg-violet-600 hover:bg-violet-700 text-white rounded-lg transition-colors font-medium text-sm"
                    >
                      Descargar Resultado
                    </button>
                  )}
                  {job.status === 'failed' && (
                    <div className="text-xs text-red-400">{job.error || 'Error desconocido'}</div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
