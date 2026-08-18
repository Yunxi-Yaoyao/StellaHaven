import { api } from "./client";

export interface DockerInfo {
  installed: boolean;
  version: string | null;
  running: boolean;
}

export interface PullProgress {
  status: "idle" | "pulling" | "done" | "failed";
  layers: { id: string; status: string; current: number; total: number }[];
  current: number;
  total: number;
  percent: number;
  error: string | null;
}

export interface StorageItem {
  name: string;
  host_path: string;
  mount_path: string;
}

export interface DriveSettings {
  port: number;
  mem_limit: string;
  cpus: string;
  tz: string;
  restart_policy: string;
}

export interface DriveStatus {
  docker: DockerInfo;
  image_exists: boolean;
  image_version: string | null;
  container_exists: boolean;
  container_running: boolean;
  container_status: string | null;
  storages: StorageItem[];
  default_storage: StorageItem;
  proxy: string;
  default_proxy: string;
  pull: PullProgress;
  settings: DriveSettings;
}

export interface CheckUpdateResult {
  local_version: string | null;
  latest_version: string | null;
  update_available: boolean;
  error: string | null;
}

export const getDriveStatus = () => api<DriveStatus>("/drive/status");
export const installDocker = () => api<DockerInfo>("/drive/docker/install", { method: "POST" });
export const pullImage = () => api<{ ok: boolean }>("/drive/pull", { method: "POST" });
export const getPullProgress = () => api<PullProgress>("/drive/pull/progress");
export const installContainer = (storages: StorageItem[], settings?: DriveSettings) =>
  api<DriveStatus>("/drive/install", {
    method: "POST",
    body: JSON.stringify({ storages, settings: settings || null }),
  });
export const getLoginUrl = () => api<{ token: string; port: number; ttl: number }>("/drive/login-url");
export const startContainer = () => api<DriveStatus>("/drive/start", { method: "POST" });
export const stopContainer = () => api<DriveStatus>("/drive/stop", { method: "POST" });
export const restartContainer = () => api<DriveStatus>("/drive/restart", { method: "POST" });
export const uninstallContainer = (removeImage: boolean) =>
  api<DriveStatus>("/drive/uninstall", { method: "POST", body: JSON.stringify({ remove_image: removeImage }) });
export const removeImage = () => api<DriveStatus>("/drive/remove-image", { method: "POST" });
export const checkUpdate = () => api<CheckUpdateResult>("/drive/check-update", { method: "POST" });
export const updateContainer = () => api<DriveStatus>("/drive/update", { method: "POST" });
export const pullLatest = () => api<DriveStatus>("/drive/pull-latest", { method: "POST" });
export const setProxy = (proxy: string) =>
  api<DriveStatus>("/drive/proxy", { method: "POST", body: JSON.stringify({ proxy }) });
