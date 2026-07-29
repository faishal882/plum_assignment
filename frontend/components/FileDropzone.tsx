"use client";

import { useState, useRef, DragEvent, ChangeEvent } from "react";
import { UploadCloud, FileText, Image as ImageIcon, X, AlertCircle } from "lucide-react";

interface FileDropzoneProps {
  files: File[];
  onFilesChange: (files: File[]) => void;
  maxSizeMb?: number;
}

export function FileDropzone({
  files,
  onFilesChange,
  maxSizeMb = 20,
}: FileDropzoneProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const allowedTypes = ["application/pdf", "image/jpeg", "image/png"];
  const maxSizeBytes = maxSizeMb * 1024 * 1024;

  const validateAndAddFiles = (newFiles: FileList | File[]) => {
    setErrorMsg(null);
    const valid: File[] = [];

    for (let i = 0; i < newFiles.length; i++) {
      const file = newFiles[i];
      if (!allowedTypes.includes(file.type)) {
        setErrorMsg(`"${file.name}" is unsupported. Only PDF, JPEG, and PNG are accepted.`);
        continue;
      }
      if (file.size > maxSizeBytes) {
        setErrorMsg(`"${file.name}" exceeds the ${maxSizeMb} MB size limit.`);
        continue;
      }
      valid.push(file);
    }

    if (valid.length > 0) {
      onFilesChange([...files, ...valid]);
    }
  };

  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files) {
      validateAndAddFiles(e.dataTransfer.files);
    }
  };

  const handleFileSelect = (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      validateAndAddFiles(e.target.files);
    }
  };

  const removeFile = (index: number) => {
    const updated = files.filter((_, i) => i !== index);
    onFilesChange(updated);
  };

  return (
    <div className="space-y-3">
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        className={`p-6 rounded-card text-center cursor-pointer border-2 border-dashed transition-all ${
          isDragging
            ? "border-violet bg-violet-pale/40 neu-inset-sm scale-[0.99]"
            : "border-hairline bg-canvas neu-inset hover:border-violet/50 hover:bg-violet-pale/20"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".pdf,.jpeg,.jpg,.png"
          onChange={handleFileSelect}
          className="hidden"
        />

        <div className="flex flex-col items-center justify-center space-y-2">
          <div className="w-12 h-12 rounded-control bg-violet-pale text-violet flex items-center justify-center neu-raised-sm">
            <UploadCloud className="w-6 h-6" />
          </div>
          <div>
            <p className="text-sm font-semibold text-ink">
              Drop claim document files here, or{" "}
              <span className="text-violet underline underline-offset-2">
                browse
              </span>
            </p>
            <p className="text-xs text-copy mt-1">
              Supports PDF, JPEG, PNG up to {maxSizeMb} MB per file (Max 10 files)
            </p>
          </div>
        </div>
      </div>

      {errorMsg && (
        <div className="flex items-center gap-2 p-2.5 rounded-control bg-danger/10 text-danger text-xs font-medium">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{errorMsg}</span>
        </div>
      )}

      {files.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-semibold text-copy uppercase tracking-wider">
            Selected Files ({files.length})
          </p>
          <div className="space-y-1.5">
            {files.map((file, idx) => (
              <div
                key={`${file.name}-${idx}`}
                className="flex items-center justify-between p-2.5 rounded-control bg-white/50 border border-hairline neu-raised-sm text-xs"
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  {file.type.includes("pdf") ? (
                    <FileText className="w-4 h-4 text-violet shrink-0" />
                  ) : (
                    <ImageIcon className="w-4 h-4 text-teal shrink-0" />
                  )}
                  <span className="font-medium text-ink truncate">
                    {file.name}
                  </span>
                  <span className="text-[11px] text-copy font-mono shrink-0">
                    ({(file.size / (1024 * 1024)).toFixed(2)} MB)
                  </span>
                </div>

                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    removeFile(idx);
                  }}
                  className="p-1 text-copy hover:text-danger rounded hover:bg-danger/10 transition-colors"
                  title="Remove file"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
