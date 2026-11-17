import data from './navigation-icons.json';

export type IconNode = [string, Record<string, string>];
export interface NavigationIcon { key: string; label: string; category: string; keywords: string; nodes: IconNode[] }
export const iconCatalog = data.icons as NavigationIcon[];
export const iconCategories: Record<string, string> = data.categories;
export const iconAliases: Record<string, string> = data.aliases;
export const navigationIcons: string[] = iconCatalog.map(icon => icon.key);
export const legacyNavigationIcons: string[] = Object.keys(iconAliases);
export const iconsByKey = new Map(iconCatalog.map(icon => [icon.key, icon]));
export function navigationIcon(key: string): NavigationIcon | undefined {
  return iconsByKey.get(iconAliases[key] ?? key);
}
