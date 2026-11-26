"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";

export default function TopBar() {
  const pathname = usePathname();
  return (
    <nav className="topbar" aria-label="Navigasi utama">
      <Link className="topbar-brand" href="/" aria-label="Video to Transcript, halaman utama">
        <Image src="/logo.webp" alt="" width={36} height={36} priority />
      </Link>
      <div className="topbar-links">
        <Link href="/" aria-current={pathname === "/" ? "page" : undefined} className={pathname === "/" ? "topbar-link topbar-link-active" : "topbar-link"}>Transkrip</Link>
        <Link href="/downloader" aria-current={pathname.startsWith("/downloader") ? "page" : undefined} className={pathname.startsWith("/downloader") ? "topbar-link topbar-link-active" : "topbar-link"}>Video Downloader</Link>
      </div>
    </nav>
  );
}
