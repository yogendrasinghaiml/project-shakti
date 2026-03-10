const STORAGE_KEY = "sp";

export async function loadMissionProgress(storageKey = STORAGE_KEY) {
  try {
    const response = await window.storage?.get(storageKey);
    return response?.value ? JSON.parse(response.value) : {};
  } catch {
    return {};
  }
}

export function saveMissionProgress(progress, storageKey = STORAGE_KEY) {
  try {
    window.storage?.set(storageKey, JSON.stringify(progress));
  } catch {}
}

export { STORAGE_KEY };
