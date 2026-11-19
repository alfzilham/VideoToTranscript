import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Video to Transcript",
  description: "Transkripsi video YouTube dan file lokal dengan timestamp menggunakan faster-whisper CPU.",
  icons: { icon: "/favicon.ico" },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="id"><body>{children}</body></html>;
}
