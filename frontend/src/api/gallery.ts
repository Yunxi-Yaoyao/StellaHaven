import { api } from "./client";

export interface DockerInfo {
  installed: boolean;
  version: string | null;
  running: boolean;
}

export interface GalleryStatus {
  docker: DockerInfo;
  container_exists: boolean;
  container_running: boolean;
  container_status: string | null;
}

export function getGalleryStatus(): Promise<GalleryStatus> {
  return api<GalleryStatus>("/gallery/status");
}

export function startContainer(): Promise<GalleryStatus> {
  return api<GalleryStatus>("/gallery/start", { method: "POST" });
}

export function stopContainer(): Promise<GalleryStatus> {
  return api<GalleryStatus>("/gallery/stop", { method: "POST" });
}

export function restartContainer(): Promise<GalleryStatus> {
  return api<GalleryStatus>("/gallery/restart", { method: "POST" });
}
