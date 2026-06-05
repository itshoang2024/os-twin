import type { NextConfig } from "next";

const configuredBackendBase = (
  process.env.OSTWIN_BACKEND_URL
  || process.env.NEXT_PUBLIC_API_BASE_URL
  || process.env.BACKEND_URL
  || 'http://localhost:3366'
);
const BACKEND_URL = configuredBackendBase
  .replace(/\/api\/?$/, '')
  .replace(/\/$/, '');

const isDev = process.env.NODE_ENV === 'development';

const nextConfig: NextConfig = {
  // Browser QA frequently uses 127.0.0.1 while Next dev advertises localhost;
  // allow both so hydration/HMR dev resources do not block client effects.
  allowedDevOrigins: ['127.0.0.1', 'localhost'],
  // Only use static export for production builds (next build).
  // In dev mode, dynamic routes work natively without generateStaticParams.
  ...(isDev ? {} : { output: 'export' }),
  images: {
    unoptimized: true,
  },
  // In dev mode (next dev), proxy /api/* requests to the FastAPI backend.
  // The backend target is configurable for QA/browser automation via
  // OSTWIN_BACKEND_URL, NEXT_PUBLIC_API_BASE_URL, or BACKEND_URL. In production
  // (static export), FastAPI serves the static frontend so /api is same-origin.
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${BACKEND_URL}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
