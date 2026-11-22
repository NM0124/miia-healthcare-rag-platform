import React from 'react';
import { Construction } from 'lucide-react';

export default function InjuryAnalysisPage() {
  return (
    <div className="min-h-[calc(100vh-64px)] bg-white flex flex-col items-center justify-center p-6 text-center">
      <div className="max-w-md w-full space-y-4">
        <div className="w-14 h-14 bg-gray-50 border border-gray-200 rounded-2xl flex items-center justify-center mx-auto text-gray-700 shadow-sm">
          <Construction className="w-7 h-7 stroke-[1.75]" />
        </div>

        <div className="space-y-1.5">
          <span className="text-[11px] font-bold text-gray-400 tracking-wider uppercase">
            Module Status
          </span>
          <h2 className="text-2xl font-bold text-gray-950 tracking-tight">
            UNDER DEVELOPMENT
          </h2>
        </div>

        <p className="text-xs text-gray-500 max-w-sm mx-auto leading-relaxed">
          AI-assisted injury image assessment and acute trauma triage protocols are currently under development. Evidence-grounded guidelines remain fully accessible in the Ask and Knowledge Base modules.
        </p>
      </div>
    </div>
  );
}

