import React, { useState, useEffect, useRef } from 'react';
import { useAuth } from '../context/AuthContext';
import {
  fetchDocumentsApi,
  uploadDocumentApi,
  deleteDocumentApi,
  bulkDeleteDocumentsApi,
} from '../api';
import {
  Search,
  ArrowUpDown,
  Plus,
  Trash2,
  AlertTriangle,
  Loader2,
  CheckSquare,
  Square,
} from 'lucide-react';

export default function KnowledgeBasePage() {
  const { user } = useAuth();
  const [documents, setDocuments] = useState([]);
  const [search, setSearch] = useState('');
  const [sortOrder, setSortOrder] = useState('desc'); // 'desc' = Newest, 'asc' = Oldest
  const [selectedIds, setSelectedIds] = useState([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);

  // Confirmation modal state
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [targetDeleteDoc, setTargetDeleteDoc] = useState(null); // single doc or null for bulk

  const fileInputRef = useRef(null);

  useEffect(() => {
    loadDocuments();
  }, [sortOrder]);

  const loadDocuments = async () => {
    setLoading(true);
    try {
      const data = await fetchDocumentsApi(search, sortOrder);
      setDocuments(data.documents || []);
    } catch (err) {
      console.error('Failed to load documents:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleSearchSubmit = (e) => {
    e.preventDefault();
    loadDocuments();
  };

  const handleToggleSort = () => {
    setSortOrder((prev) => (prev === 'desc' ? 'asc' : 'desc'));
  };

  const handleSelectAll = () => {
    if (selectedIds.length === documents.length) {
      setSelectedIds([]);
    } else {
      setSelectedIds(documents.map((d) => d.id));
    }
  };

  const handleToggleSelect = (id) => {
    if (selectedIds.includes(id)) {
      setSelectedIds(selectedIds.filter((item) => item !== id));
    } else {
      setSelectedIds([...selectedIds, id]);
    }
  };

  const handleFileUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploading(true);
    try {
      await uploadDocumentApi(file);
      loadDocuments();
    } catch (err) {
      alert('Upload failed. Please try again.');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  // Trigger single deletion with confirmation
  const promptSingleDelete = (doc) => {
    setTargetDeleteDoc(doc);
    setShowConfirmModal(true);
  };

  // Trigger bulk deletion with confirmation
  const promptBulkDelete = () => {
    if (selectedIds.length === 0) return;
    setTargetDeleteDoc(null); // indicates bulk
    setShowConfirmModal(true);
  };

  // Confirm and execute deletion
  const executeDelete = async () => {
    setShowConfirmModal(false);
    setLoading(true);
    try {
      if (targetDeleteDoc) {
        // Individual deletion
        await deleteDocumentApi(targetDeleteDoc.id);
        setSelectedIds((prev) => prev.filter((id) => id !== targetDeleteDoc.id));
      } else {
        // Bulk deletion
        await bulkDeleteDocumentsApi(selectedIds);
        setSelectedIds([]);
      }
      await loadDocuments();
    } catch (err) {
      alert('Deletion error. Please try again.');
    } finally {
      setLoading(false);
      setTargetDeleteDoc(null);
    }
  };

  const formatDate = (isoString) => {
    if (!isoString) return 'Oct 12, 2023';
    try {
      const d = new Date(isoString);
      return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    } catch {
      return isoString ? isoString.slice(0, 10) : '';
    }
  };

  return (
    <div className="max-w-7xl mx-auto px-8 py-10 w-full min-h-[calc(100vh-64px)] bg-white">
      {/* Hidden File Input */}
      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileUpload}
        className="hidden"
        accept=".pdf,.jpg,.jpeg,.png,.docx,.xlsx"
      />

      {/* Top Action Bar */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-4 mb-8">
        {/* Search Input */}
        <form onSubmit={handleSearchSubmit} className="relative w-full sm:w-80">
          <Search className="w-4 h-4 text-gray-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onBlur={loadDocuments}
            placeholder="Search"
            className="w-full pl-10 pr-4 py-2 border border-gray-200 rounded-xl text-xs text-gray-900 placeholder-gray-400 focus:outline-none focus:border-gray-400 transition-all bg-white"
          />
        </form>

        {/* Action Controls: Sort, Delete (beside sort), + Upload New */}
        <div className="flex items-center space-x-3 w-full sm:w-auto justify-end">
          {/* Sort Button */}
          <button
            onClick={handleToggleSort}
            className="flex items-center space-x-1.5 px-3.5 py-2 border border-gray-200 hover:border-gray-300 rounded-xl text-xs font-semibold text-gray-700 bg-white transition-all shadow-sm"
          >
            <ArrowUpDown className="w-3.5 h-3.5 text-gray-500" />
            <span>Sort ({sortOrder === 'desc' ? 'Newest' : 'Oldest'})</span>
          </button>

          {/* Delete Button (Beside Sort) */}
          <button
            onClick={promptBulkDelete}
            disabled={selectedIds.length === 0}
            className={`flex items-center space-x-1.5 px-3.5 py-2 rounded-xl text-xs font-semibold transition-all ${
              selectedIds.length > 0
                ? 'bg-red-50 text-red-600 border border-red-200 hover:bg-red-100 cursor-pointer shadow-sm'
                : 'bg-gray-50 text-gray-300 border border-gray-100 cursor-not-allowed'
            }`}
          >
            <Trash2 className="w-3.5 h-3.5" />
            <span>Delete {selectedIds.length > 0 ? `(${selectedIds.length})` : ''}</span>
          </button>

          {/* Upload New Button */}
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            className="flex items-center space-x-1.5 bg-[#18181B] hover:bg-black text-white px-5 py-2 rounded-xl text-xs font-semibold transition-all shadow-sm"
          >
            {uploading ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Plus className="w-3.5 h-3.5 stroke-[2.5]" />
            )}
            <span>{uploading ? 'Processing...' : 'Upload New'}</span>
          </button>
        </div>
      </div>

      {/* Document Table */}
      <div className="w-full overflow-x-auto border border-gray-200 rounded-2xl shadow-sm bg-white">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-gray-200 bg-gray-50/50 text-[11px] font-bold text-gray-400 uppercase tracking-wider">
              {/* Bulk Select Checkbox */}
              <th className="py-3.5 px-6 w-12 text-center">
                <button
                  type="button"
                  onClick={handleSelectAll}
                  className="text-gray-400 hover:text-gray-700 focus:outline-none"
                >
                  {documents.length > 0 && selectedIds.length === documents.length ? (
                    <CheckSquare className="w-4 h-4 text-gray-900" />
                  ) : (
                    <Square className="w-4 h-4" />
                  )}
                </button>
              </th>
              <th className="py-3.5 px-6 font-semibold">NAME</th>
              <th className="py-3.5 px-6 font-semibold">SIZE</th>
              <th className="py-3.5 px-6 font-semibold text-center">STATUS</th>
              <th className="py-3.5 px-6 font-semibold">UPLOADED</th>
              <th className="py-3.5 px-6 font-semibold text-right">ACTION</th>
            </tr>
          </thead>

          <tbody className="divide-y divide-gray-100 text-xs text-gray-700 font-medium">
            {loading ? (
              <tr>
                <td colSpan={6} className="py-12 text-center text-gray-400">
                  <Loader2 className="w-6 h-6 animate-spin mx-auto mb-2 text-gray-500" />
                  <span>Loading documents...</span>
                </td>
              </tr>
            ) : documents.length === 0 ? (
              <tr>
                <td colSpan={6} className="py-16 text-center text-gray-400">
                  No documents found. Click <span className="font-semibold text-gray-700">Upload New</span> to add medical reports or guidelines.
                </td>
              </tr>
            ) : (
              documents.map((doc) => {
                const isSelected = selectedIds.includes(doc.id);
                const isIndexed = doc.status === 'indexed';

                return (
                  <tr
                    key={doc.id}
                    className={`hover:bg-gray-50/80 transition-colors ${
                      isSelected ? 'bg-blue-50/30' : ''
                    }`}
                  >
                    {/* Row Checkbox */}
                    <td className="py-4 px-6 text-center">
                      <button
                        type="button"
                        onClick={() => handleToggleSelect(doc.id)}
                        className="text-gray-400 hover:text-gray-700 focus:outline-none"
                      >
                        {isSelected ? (
                          <CheckSquare className="w-4 h-4 text-gray-900" />
                        ) : (
                          <Square className="w-4 h-4" />
                        )}
                      </button>
                    </td>

                    {/* Name */}
                    <td className="py-4 px-6 font-semibold text-gray-900 truncate max-w-xs">
                      {doc.file_name}
                    </td>

                    {/* Size */}
                    <td className="py-4 px-6 text-gray-500">{doc.file_size}</td>

                    {/* Status Badge */}
                    <td className="py-4 px-6 text-center">
                      <span
                        className={`inline-block px-2.5 py-0.5 rounded-md text-[10px] font-bold tracking-wider uppercase ${
                          isIndexed
                            ? 'bg-gray-100 text-gray-700'
                            : 'bg-purple-50 text-purple-600'
                        }`}
                      >
                        {doc.status || 'INDEXED'}
                      </span>
                    </td>

                    {/* Uploaded Date */}
                    <td className="py-4 px-6 text-gray-500">{formatDate(doc.upload_date)}</td>

                    {/* Action: DELETE */}
                    <td className="py-4 px-6 text-right">
                      <button
                        onClick={() => promptSingleDelete(doc)}
                        className="text-[11px] font-bold text-gray-700 hover:text-red-600 tracking-wider uppercase transition-colors"
                      >
                        DELETE
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Confirmation Modal: ARE YOU SURE? */}
      {showConfirmModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm animate-in fade-in duration-150">
          <div className="bg-white rounded-2xl shadow-2xl border border-gray-100 max-w-md w-full mx-4 p-7 space-y-4">
            <div className="flex items-center space-x-3 text-red-600">
              <div className="w-10 h-10 rounded-full bg-red-50 flex items-center justify-center">
                <AlertTriangle className="w-5 h-5 text-red-600" />
              </div>
              <h3 className="text-lg font-bold text-gray-900 tracking-tight">ARE YOU SURE?</h3>
            </div>

            <p className="text-xs text-gray-600 leading-relaxed">
              {targetDeleteDoc ? (
                <>
                  Are you sure you want to permanently delete{' '}
                  <span className="font-semibold text-gray-900">"{targetDeleteDoc.file_name}"</span>?
                  This action will completely remove the document, its chunks, and associated embeddings from ChromaDB storage.
                </>
              ) : (
                <>
                  Are you sure you want to permanently delete all{' '}
                  <span className="font-semibold text-gray-900">{selectedIds.length}</span> selected
                  documents? Their original files, chunks, and embeddings will be removed from storage.
                </>
              )}
            </p>

            <div className="flex items-center justify-end space-x-3 pt-4 border-t border-gray-100">
              <button
                onClick={() => {
                  setShowConfirmModal(false);
                  setTargetDeleteDoc(null);
                }}
                className="px-4 py-2 border border-gray-200 hover:bg-gray-50 rounded-xl text-xs font-semibold text-gray-700 transition-all"
              >
                Cancel
              </button>
              <button
                onClick={executeDelete}
                className="px-5 py-2 bg-red-600 hover:bg-red-700 text-white rounded-xl text-xs font-semibold transition-all shadow-sm"
              >
                Confirm
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
