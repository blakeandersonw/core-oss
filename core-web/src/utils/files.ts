import type { Document } from '../api/client';

const BAD_FETCH_TITLE = 'failed to fetch';

function cleanText(value: string | null | undefined): string {
  return (value || '').trim();
}

function isBadGeneratedTitle(value: string | null | undefined): boolean {
  const title = cleanText(value);
  return title.length === 0 || title.toLowerCase() === BAD_FETCH_TITLE;
}

function isFileDocument(doc: Document): boolean {
  return !doc.is_folder && doc.type !== 'folder' && (
    doc.type === 'file' ||
    !!doc.file_id ||
    !!doc.file ||
    !!doc.file_url ||
    !!doc.file_type
  );
}

export function getDocumentDisplayTitle(doc: Document, fallback = 'Untitled'): string {
  const title = cleanText(doc.title);

  if (!isFileDocument(doc)) {
    return title || fallback;
  }

  if (!isBadGeneratedTitle(title)) {
    return title;
  }

  const filename = cleanText(doc.file?.filename);
  if (!isBadGeneratedTitle(filename)) {
    return filename;
  }

  return 'Untitled file';
}

export function getGeneratedFileTitleRepair(doc: Document): string | null {
  const title = cleanText(doc.title);
  if (!isFileDocument(doc) || title.toLowerCase() !== BAD_FETCH_TITLE) {
    return null;
  }

  const filename = cleanText(doc.file?.filename);
  return isBadGeneratedTitle(filename) ? null : filename;
}

function extensionForMimeType(mimeType: string): string {
  const normalized = mimeType.toLowerCase();
  const explicit: Record<string, string> = {
    'image/jpeg': 'jpg',
    'image/png': 'png',
    'image/gif': 'gif',
    'image/webp': 'webp',
    'image/heic': 'heic',
    'image/heif': 'heif',
    'application/pdf': 'pdf',
    'text/plain': 'txt',
    'text/csv': 'csv',
    'text/markdown': 'md',
    'audio/mpeg': 'mp3',
    'audio/wav': 'wav',
    'video/mp4': 'mp4',
  };

  if (explicit[normalized]) return explicit[normalized];

  const subtype = normalized.split('/')[1]?.split(';')[0];
  return subtype?.replace(/[^a-z0-9]+/g, '') || 'bin';
}

function fallbackBaseForMimeType(mimeType: string): string {
  const family = mimeType.toLowerCase().split('/')[0];
  if (family === 'image') return 'image';
  if (family === 'video') return 'video';
  if (family === 'audio') return 'audio';
  return 'file';
}

export function getSafeUploadFilename(
  file: Pick<File, 'name' | 'type'>,
  timestamp = Date.now(),
): string {
  const name = cleanText(file.name);
  if (!isBadGeneratedTitle(name)) {
    return name;
  }

  const mimeType = file.type || 'application/octet-stream';
  return `${fallbackBaseForMimeType(mimeType)}-${timestamp}.${extensionForMimeType(mimeType)}`;
}
