import { useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../api';

const STATUS_STYLES = {
  valid: 'text-emerald-700 bg-emerald-50 border-emerald-200',
  invalid: 'text-red-700 bg-red-50 border-red-200',
  duplicate_in_file: 'text-amber-700 bg-amber-50 border-amber-200',
  existing_in_db: 'text-blue-700 bg-blue-50 border-blue-200',
};

const STATUS_LABELS = {
  valid: 'Ready to Import',
  invalid: 'Invalid Row',
  duplicate_in_file: 'Duplicate in File',
  existing_in_db: 'Already in Database',
};

export default function ExcelImport() {
  const navigate = useNavigate();
  const fileInputRef = useRef(null);
  const [step, setStep] = useState('upload');
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState(null);
  const [error, setError] = useState('');
  const [dragOver, setDragOver] = useState(false);

  const handleFileChange = (e) => {
    const selected = e.target.files[0];
    if (selected) {
      setFile(selected);
      setError('');
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      setFile(e.dataTransfer.files[0]);
      setError('');
    }
  };

  const handleUpload = async () => {
    if (!file) {
      setError('Please select a file first');
      return;
    }

    setError('');
    setImporting(true);

    try {
      const formData = new FormData();
      formData.append('file', file);
      const res = await api.post('/import/excel', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setPreview(res.data);
      setStep('preview');
    } catch (err) {
      setError(err.message);
    } finally {
      setImporting(false);
    }
  };

  const handleConfirm = async () => {
    setImporting(true);
    setError('');

    try {
      const res = await api.post(`/import/${preview.batchId}/confirm`);
      setImportResult(res.data);
      setStep('complete');
    } catch (err) {
      setError(err.message);
    } finally {
      setImporting(false);
    }
  };

  const handleCancel = () => {
    setFile(null);
    setPreview(null);
    setError('');
    setStep('upload');
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  return (
    <div className="space-y-8 animate-fadeIn max-w-4xl mx-auto">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-black tracking-tight text-slate-900">Excel Lead Ingestion</h1>
        <p className="text-xs text-slate-500 mt-0.5">
          Upload spreadsheets to automatically map column headers, validate URLs, and commit companies to your pipeline.
        </p>
      </div>

      {/* Modern Stepper */}
      <div className="flex items-center justify-between bg-white rounded-2xl border border-slate-200/80 p-4 shadow-xs">
        {[
          { id: 'upload', num: '1', label: 'Upload File', desc: 'Select Excel or CSV' },
          { id: 'preview', num: '2', label: 'Preview & Validate', desc: 'Auto-header mapping' },
          { id: 'complete', num: '3', label: 'Pipeline Commit', desc: 'Ingested into DB' },
        ].map((s, i) => {
          const stepIndex = { upload: 0, preview: 1, complete: 2 }[step] || 0;
          const isActive = i === stepIndex;
          const isDone = i < stepIndex;
          return (
            <div key={s.id} className="flex items-center gap-3 flex-1">
              <div className={`w-9 h-9 rounded-xl flex items-center justify-center font-bold text-xs transition-all ${
                isDone ? 'bg-emerald-500 text-white shadow-xs' : isActive ? 'bg-indigo-600 text-white shadow-md shadow-indigo-500/20' : 'bg-slate-100 text-slate-400'
              }`}>
                {isDone ? '✓' : s.num}
              </div>
              <div className="hidden sm:block">
                <p className={`text-xs font-bold ${isActive ? 'text-slate-900' : 'text-slate-500'}`}>{s.label}</p>
                <p className="text-[10px] text-slate-400">{s.desc}</p>
              </div>
              {i < 2 && <div className="flex-1 h-0.5 bg-slate-100 mx-3 hidden md:block" />}
            </div>
          );
        })}
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-2xl text-xs flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError('')} className="font-bold text-red-500">&times;</button>
        </div>
      )}

      {/* Step 1: Upload */}
      {step === 'upload' && (
        <div className="space-y-6">
          <div
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            className={`border-2 border-dashed rounded-3xl p-12 text-center transition-all bg-white cursor-pointer ${
              dragOver ? 'border-indigo-500 bg-indigo-50/50 scale-101' : 'border-slate-300 hover:border-indigo-400 hover:bg-slate-50/50'
            }`}
            onClick={() => fileInputRef.current?.click()}
          >
            <input
              type="file"
              ref={fileInputRef}
              accept=".xlsx,.xls,.csv"
              onChange={handleFileChange}
              className="hidden"
            />
            <div className="w-16 h-16 rounded-2xl bg-indigo-50 text-indigo-600 flex items-center justify-center text-3xl mx-auto mb-4 shadow-sm">
              📊
            </div>
            <p className="font-bold text-slate-900 text-base">
              {file ? file.name : 'Click to select or drag & drop your Excel spreadsheet'}
            </p>
            <p className="text-xs text-slate-500 mt-1">
              Supports .xlsx, .xls, and .csv files up to 10MB
            </p>

            <div className="flex justify-center gap-2 mt-6">
              {['Company Name', 'Website URL', 'Industry', 'Contact Email', 'Contact Name'].map((tag) => (
                <span key={tag} className="text-[10px] font-bold text-slate-500 bg-slate-100 px-2.5 py-1 rounded-full border border-slate-200">
                  {tag}
                </span>
              ))}
            </div>

            <div className="mt-4">
              <a
                href="/api/import/template"
                download
                className="inline-flex items-center gap-1.5 text-[11px] font-bold text-indigo-600 hover:text-indigo-800 underline decoration-dotted"
              >
                ⬇️ Download Import Template (.xlsx)
              </a>
            </div>
          </div>

          <div className="flex justify-end gap-3">
            <button
              type="button"
              onClick={handleUpload}
              disabled={!file || importing}
              className="px-6 py-2.5 bg-gradient-to-r from-indigo-600 to-blue-600 hover:from-indigo-700 hover:to-blue-700 text-white rounded-xl text-xs font-bold transition-all shadow-md shadow-indigo-600/20 disabled:opacity-50 flex items-center gap-2"
            >
              <span>{importing ? '⏳' : '⚡'}</span>
              <span>{importing ? 'Parsing Excel Rows...' : 'Analyze & Preview File'}</span>
            </button>
          </div>
        </div>
      )}

      {/* Step 2: Preview */}
      {step === 'preview' && preview && (
        <div className="space-y-6">
          <div className="bg-white rounded-2xl border border-slate-200/80 p-5 shadow-xs flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
            <div>
              <h3 className="font-bold text-slate-900 text-sm">Batch Validation Summary</h3>
              <p className="text-xs text-slate-500 mt-0.5">
                Total Rows: <span className="font-bold text-slate-900">{preview.totalRows}</span> | Ready:{' '}
                <span className="font-bold text-emerald-600">{preview.validRows}</span> | Duplicates / Skipped:{' '}
                <span className="font-bold text-amber-600">{preview.duplicateRows}</span>
              </p>
            </div>

            <div className="flex gap-2">
              <button
                onClick={handleCancel}
                className="px-4 py-2 border border-slate-200 text-slate-700 hover:bg-slate-50 rounded-xl text-xs font-bold transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => window.open(`/api/import/${preview.batchId}/invalid-report`, '_blank')}
                disabled={importing || !preview.summary?.invalid}
                title="Download a .xlsx report of the rows that need fixes"
                className="px-4 py-2 border border-amber-300 text-amber-700 hover:bg-amber-50 rounded-xl text-xs font-bold transition-colors disabled:opacity-50 flex items-center gap-1.5"
              >
                ⬇️ Validation Report
              </button>
              <button
                onClick={handleConfirm}
                disabled={importing || preview.validRows === 0}
                className="px-5 py-2 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-700 hover:to-teal-700 text-white rounded-xl text-xs font-bold shadow-md disabled:opacity-50 flex items-center gap-1.5"
              >
                <span>✓</span>
                <span>{importing ? 'Committing...' : `Commit ${preview.validRows} Companies`}</span>
              </button>
            </div>
          </div>

          <div className="bg-white rounded-2xl border border-slate-200/80 overflow-hidden shadow-xs">
            <div className="overflow-x-auto max-h-96">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-50 border-b border-slate-200 text-[10px] font-bold text-slate-500 uppercase tracking-wider sticky top-0">
                  <tr>
                    <th className="px-4 py-3">Row #</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Company Name</th>
                    <th className="px-4 py-3">Website</th>
                    <th className="px-4 py-3">Evidence</th>
                    <th className="px-4 py-3">Recommended Service</th>
                    <th className="px-4 py-3">Validation / Errors</th>
                    <th className="px-4 py-3">Suggested Fix</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {preview.rows?.slice(0, 50).map((r, i) => (
                    <tr key={i} className="hover:bg-slate-50/80">
                      <td className="px-4 py-3 text-slate-400 font-mono text-[11px]">{r.rowNumber || i + 1}</td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border ${STATUS_STYLES[r.status] || STATUS_STYLES.valid}`}>
                          {STATUS_LABELS[r.status] || r.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-bold text-slate-900">{r.companyName || r.data?.companyName || '—'}</td>
                      <td className="px-4 py-3 text-indigo-600 font-mono text-[11px] truncate max-w-xs">{r.website || r.data?.website || '—'}</td>
                      <td className="px-4 py-3 text-slate-700 text-[11px] max-w-xs truncate" title={r.evidence || r.data?.evidence}>
                        {r.evidence || r.data?.evidence || <span className="text-slate-400 italic">None</span>}
                      </td>
                      <td className="px-4 py-3 text-slate-700 text-[11px]">
                        {r.recommendedService || r.data?.recommendedService ? (
                          <span className="flex flex-col items-start gap-1">
                            <span className="inline-block bg-slate-100 px-2 py-0.5 rounded text-[10px] font-medium text-slate-800">
                              {r.recommendedService || r.data?.recommendedService}
                            </span>
                            {r.serviceMapped && (
                              <span className="inline-block bg-indigo-50 text-indigo-600 border border-indigo-200 px-2 py-0.5 rounded text-[9px] font-semibold">
                                ← mapped from “{r.originalService}”
                              </span>
                            )}
                          </span>
                        ) : (
                          <span className="text-slate-400 italic">None</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-slate-500 text-[11px]">
                        {r.validationErrors && r.validationErrors.length > 0 ? (
                          <span className="text-red-600 font-medium">
                            {r.validationErrors.join(', ')}
                          </span>
                        ) : (
                          <span className="text-emerald-600 font-medium">Pass</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-slate-500 text-[11px]">
                        {r.suggestedFix && r.suggestedFix.length > 0 ? (
                          <span className="text-amber-700 font-medium">
                            {r.suggestedFix.join(', ')}
                          </span>
                        ) : (
                          <span className="text-slate-300 italic">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Step 3: Complete */}
      {step === 'complete' && importResult && (
        <div className="bg-white rounded-3xl border border-slate-200 p-12 text-center shadow-sm space-y-4">
          <div className="w-16 h-16 rounded-full bg-emerald-100 text-emerald-600 flex items-center justify-center text-3xl mx-auto shadow-sm">
            🎉
          </div>
          <h2 className="text-xl font-extrabold text-slate-900">Import Batch Committed Successfully!</h2>
          <p className="text-xs text-slate-500 max-w-md mx-auto">
            {importResult.importedCount || preview?.validRows} new companies have been added to your pipeline directory. You can now trigger automated crawling and precision AI research.
          </p>

          <div className="pt-4 flex justify-center gap-3">
            <button
              onClick={handleCancel}
              className="px-4 py-2 border border-slate-200 text-slate-700 hover:bg-slate-50 rounded-xl text-xs font-bold"
            >
              Upload Another File
            </button>
            <button
              onClick={() => navigate('/companies')}
              className="px-6 py-2 bg-gradient-to-r from-indigo-600 to-blue-600 hover:from-indigo-700 hover:to-blue-700 text-white rounded-xl text-xs font-bold shadow-md"
            >
              Open Company Pipeline &rarr;
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
