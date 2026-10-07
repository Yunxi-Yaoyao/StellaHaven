export type DriveBackgroundMode='solid'|'image';
export const DRIVE_BACKGROUND_KEY='stella_drive_bg_mode';
export const LEGACY_DRIVE_BACKGROUND_KEY='__stella_drive_bg_mode__';
export const DRIVE_BACKGROUND_EVENT='stella-drive-background';
const valid=(value:unknown):value is DriveBackgroundMode=>value==='solid'||value==='image';
// Reading never changes either preference; the outer key wins when both exist.
export function readDriveBackground():DriveBackgroundMode {
 try{const current=localStorage.getItem(DRIVE_BACKGROUND_KEY);if(valid(current))return current;
 const legacy=localStorage.getItem(LEGACY_DRIVE_BACKGROUND_KEY);return valid(legacy)?legacy:'solid';}
 catch{return 'solid';}
}
export function saveDriveBackground(mode:DriveBackgroundMode){
 localStorage.setItem(DRIVE_BACKGROUND_KEY,mode);
 localStorage.setItem(LEGACY_DRIVE_BACKGROUND_KEY,mode);
 window.dispatchEvent(new Event(DRIVE_BACKGROUND_EVENT));
}
