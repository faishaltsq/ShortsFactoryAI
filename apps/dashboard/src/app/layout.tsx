import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Shorts Factory — Pixel Production Studio',
  description: 'Konsol produksi lokal untuk pipeline YouTube Shorts.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="id">
      <body>{children}</body>
    </html>
  );
}
