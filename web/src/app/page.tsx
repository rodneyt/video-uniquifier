"use client";

import { useState } from 'react';
import { useRouter } from 'next/navigation';

export default function Home() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({ username: email, password })
      });
      if (res.ok) {
        const data = await res.json();
        localStorage.setItem('token', data.access_token);
        router.push('/dashboard');
      } else {
        alert('Credenciales inválidas');
      }
    } catch (_) {
      alert('Error de conexión');
    }
    setLoading(false);
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-50 flex flex-col items-center justify-center p-4">
      <div className="w-full max-w-md space-y-8">
        <div className="text-center">
          <h1 className="text-4xl font-extrabold tracking-tight lg:text-5xl bg-gradient-to-r from-violet-400 to-fuchsia-400 bg-clip-text text-transparent">
            Video Uniquifier
          </h1>
          <p className="mt-4 text-lg text-slate-400">
            Evade la detección de contenido duplicado en TikTok e Instagram con nuestro pipeline avanzado.
          </p>
        </div>

        <form onSubmit={handleLogin} className="mt-8 space-y-6 bg-slate-900 p-8 rounded-2xl shadow-xl border border-slate-800">
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-slate-300">Email</label>
              <input
                type="email"
                required
                className="mt-1 block w-full px-4 py-3 bg-slate-950 border border-slate-800 rounded-xl focus:ring-2 focus:ring-violet-500 focus:border-violet-500 transition-colors"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-300">Contraseña</label>
              <input
                type="password"
                required
                className="mt-1 block w-full px-4 py-3 bg-slate-950 border border-slate-800 rounded-xl focus:ring-2 focus:ring-violet-500 focus:border-violet-500 transition-colors"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full flex justify-center py-3 px-4 border border-transparent rounded-xl shadow-sm text-sm font-bold text-white bg-violet-600 hover:bg-violet-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-violet-500 disabled:opacity-50 transition-colors"
          >
            {loading ? 'Iniciando...' : 'Iniciar Sesión'}
          </button>
        </form>
      </div>
    </div>
  );
}
