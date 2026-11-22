/**
 * API client for MIIA backend.
 */

const API_BASE = '/api';

export function getAuthHeaders() {
  const token = localStorage.getItem('miia_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function googleLoginApi(credential) {
  const res = await fetch(`${API_BASE}/auth/google`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ credential }),
  });
  if (!res.ok) throw new Error('Login failed');
  return res.json();
}

export async function fetchCurrentUserApi() {
  const res = await fetch(`${API_BASE}/auth/me`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error('Session invalid');
  return res.json();
}

export async function logoutApi() {
  try {
    await fetch(`${API_BASE}/auth/logout`, {
      method: 'POST',
      headers: getAuthHeaders(),
    });
  } catch (e) {
    // ignore
  }
}

// -----------------------------------------------------------------------------
// Chat APIs
// -----------------------------------------------------------------------------

export async function fetchChatSessionsApi() {
  const res = await fetch(`${API_BASE}/chat/sessions`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error('Failed to load sessions');
  return res.json();
}

export async function createChatSessionApi(title = 'New Chat') {
  const res = await fetch(`${API_BASE}/chat/sessions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
    },
    body: JSON.stringify({ title }),
  });
  if (!res.ok) throw new Error('Failed to create session');
  return res.json();
}

export async function deleteChatSessionApi(sessionId) {
  const res = await fetch(`${API_BASE}/chat/sessions/${sessionId}`, {
    method: 'DELETE',
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error('Failed to delete session');
  return res.json();
}

export async function fetchMessagesApi(sessionId) {
  const res = await fetch(`${API_BASE}/chat/sessions/${sessionId}/messages`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error('Failed to load messages');
  return res.json();
}

export async function sendMessageApi(sessionId, message) {
  const res = await fetch(`${API_BASE}/chat/sessions/${sessionId}/messages`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
    },
    body: JSON.stringify({ message }),
  });
  if (!res.ok) throw new Error('Failed to send message');
  return res.json();
}

// -----------------------------------------------------------------------------
// Document Library APIs
// -----------------------------------------------------------------------------

export async function fetchDocumentsApi(search = '', sort = 'desc') {
  const params = new URLSearchParams();
  if (search) params.append('search', search);
  if (sort) params.append('sort', sort);

  const res = await fetch(`${API_BASE}/documents?${params.toString()}`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error('Failed to fetch documents');
  return res.json();
}

export async function uploadDocumentApi(file, sessionId = '') {
  const formData = new FormData();
  formData.append('file', file);

  const url = sessionId 
    ? `${API_BASE}/documents/upload?session_id=${encodeURIComponent(sessionId)}`
    : `${API_BASE}/documents/upload`;

  const res = await fetch(url, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: formData,
  });
  if (!res.ok) throw new Error('Upload failed');
  return res.json();
}

export async function deleteDocumentApi(docId) {
  const res = await fetch(`${API_BASE}/documents/${docId}`, {
    method: 'DELETE',
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error('Failed to delete document');
  return res.json();
}

export async function bulkDeleteDocumentsApi(docIds) {
  const res = await fetch(`${API_BASE}/documents/bulk-delete`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeaders(),
    },
    body: JSON.stringify({ document_ids: docIds }),
  });
  if (!res.ok) throw new Error('Bulk delete failed');
  return res.json();
}

