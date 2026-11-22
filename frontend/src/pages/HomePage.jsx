import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { Check, ChevronDown, ChevronUp, FileText, Image as ImageIcon } from 'lucide-react';

const FAQS = [
  {
    q: 'What is MIIA?',
    a: 'MIIA is a healthcare intelligence RAG platform that combines medical knowledge retrieval, document analysis and AI-assisted injury image assessment.',
  },
  {
    q: 'Where does MIIA gets its medical information?',
    a: 'MIIA uses a curated knowledge base built from healthcare resources and guidelines published by organisations such as WHO, NHM and CDC.',
  },
  {
    q: 'Does MIIA provide medical diagnoses?',
    a: 'No. MIIA provides informational responses and AI-assisted preliminary assessments. It is not designed to replace professional medical diagnosis or clinical judgement.',
  },
  {
    q: 'Can I upload medical reports?',
    a: 'Yes. Users can upload supported medical documents and reports for information extraction.',
  },
];

export default function HomePage({ onGetStarted }) {
  const { user, openLogin } = useAuth();
  const [openFaq, setOpenFaq] = useState([0]); // all open by default as in design

  const toggleFaq = (idx) => {
    if (openFaq.includes(idx)) {
      setOpenFaq(openFaq.filter((i) => i !== idx));
    } else {
      setOpenFaq([...openFaq, idx]);
    }
  };

  const handleAction = () => {
    if (user) {
      onGetStarted();
    } else {
      openLogin();
    }
  };

  return (
    <div className="min-h-screen bg-white flex flex-col justify-between">
      {/* Hero Section */}
      <section className="max-w-7xl mx-auto px-6 pt-16 pb-20 w-full">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-12 items-center">
          {/* Left Column Text */}
          <div className="lg:col-span-7 space-y-6">
            <p className="text-[11px] font-semibold tracking-wider text-gray-500 uppercase bg-gray-50 px-3 py-1.5 rounded-md inline-block border border-gray-100">
              Medical Intelligence and Injury Analysis
            </p>

            <h1 className="text-5xl sm:text-6xl font-extrabold text-gray-950 tracking-tight leading-[1.1]">
              Healthcare RAG<br />
              Platform and<br />
              Injury Analysis
            </h1>

            <p className="text-base text-gray-600 max-w-xl leading-relaxed">
              MIIA provides evidence-grounded healthcare information through RAG-based retrieval and AI-assisted injury analysis.
            </p>

            <div className="space-y-2.5 pt-2">
              <div className="flex items-center space-x-2.5 text-sm text-gray-700 font-medium">
                <Check className="w-4 h-4 text-gray-900 stroke-[2.5]" />
                <span>Evidence-Grounded Healthcare Information</span>
              </div>
              <div className="flex items-center space-x-2.5 text-sm text-gray-700 font-medium">
                <Check className="w-4 h-4 text-gray-900 stroke-[2.5]" />
                <span>AI-assisted Injury Image Analysis <span className="text-xs text-gray-500 font-normal">(IN DEVELOPMENT)</span></span>
              </div>
            </div>

            <div className="pt-4">
              <button
                onClick={handleAction}
                className="bg-gray-950 hover:bg-black text-white text-sm font-medium px-7 py-3 rounded-full transition-all shadow-sm hover:shadow-md"
              >
                Get started
              </button>
            </div>
          </div>

          {/* Right Column: Knowledge Base Card Preview */}
          <div className="lg:col-span-5 flex justify-center lg:justify-end">
            <div className="w-full max-w-md bg-white rounded-2xl border border-gray-200 shadow-xl overflow-hidden p-6 space-y-4">
              <div className="border-b border-gray-100 pb-3">
                <h4 className="text-sm font-semibold text-gray-900">Knowledge Base</h4>
              </div>

              <div className="space-y-3">
                {/* Row 1 */}
                <div className="flex items-center justify-between p-3 rounded-xl border border-gray-100 bg-gray-50/50">
                  <div className="flex items-center space-x-3">
                    <span className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 bg-blue-50 text-blue-600 rounded">
                      PDF
                    </span>
                    <span className="text-xs font-medium text-gray-800">lab_results.pdf</span>
                  </div>
                  <span className="text-[11px] font-medium text-gray-400">processing</span>
                </div>

                {/* Row 2 */}
                <div className="flex items-center justify-between p-3 rounded-xl border border-gray-100 bg-gray-50/50">
                  <div className="flex items-center space-x-3">
                    <span className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 bg-blue-50 text-blue-600 rounded">
                      PDF
                    </span>
                    <span className="text-xs font-medium text-gray-800">medical_guidelines.pdf</span>
                  </div>
                  <span className="text-[11px] font-medium text-gray-400">processing</span>
                </div>

                {/* Row 3 */}
                <div className="flex items-center justify-between p-3 rounded-xl border border-gray-100 bg-gray-50/50">
                  <div className="flex items-center space-x-3">
                    <span className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 bg-purple-50 text-purple-600 rounded">
                      IMG
                    </span>
                    <span className="text-xs font-medium text-gray-800">lab_results.jpg</span>
                  </div>
                  <span className="text-[11px] font-medium text-emerald-600">indexed</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* 3-Column Value Props Banner */}
      <section className="w-full bg-[#F3F4F6] py-10 border-y border-gray-200">
        <div className="max-w-7xl mx-auto px-6 grid grid-cols-1 md:grid-cols-3 gap-8">
          <div>
            <h3 className="text-base font-bold text-gray-900 mb-1.5">BGE-M3</h3>
            <p className="text-xs text-gray-600 leading-relaxed">
              1024-dimensional embeddings for semantic representation and retrieval of medical information
            </p>
          </div>

          <div>
            <h3 className="text-base font-bold text-gray-900 mb-1.5">Hybrid Retrieval Pipeline</h3>
            <p className="text-xs text-gray-600 leading-relaxed">
              Dense semantic search and BM25 keyword search using RRF, followed by BGE Reranking for improved retrieval relevance
            </p>
          </div>

          <div>
            <h3 className="text-base font-bold text-gray-900 mb-2">Trusted Sources</h3>
            <div className="flex items-center space-x-5 text-gray-700 font-bold text-sm tracking-wide">
              <span>WHO</span>
              <span>NHM</span>
              <span>CDC</span>
            </div>
          </div>
        </div>
      </section>

      {/* Frequently Asked Questions */}
      <section className="max-w-4xl mx-auto px-6 py-16 w-full">
        <h2 className="text-2xl font-bold text-gray-950 mb-8">Frequently asked questions</h2>

        <div className="space-y-4">
          {FAQS.map((faq, idx) => {
            const isOpen = openFaq.includes(idx);
            return (
              <div
                key={idx}
                className="border border-gray-200 rounded-xl overflow-hidden transition-all"
              >
                <button
                  onClick={() => toggleFaq(idx)}
                  className="w-full px-5 py-4 text-left flex items-center justify-between bg-white hover:bg-gray-50/70 transition-colors"
                >
                  <span className="text-sm font-semibold text-gray-900">{faq.q}</span>
                  {isOpen ? (
                    <ChevronUp className="w-4 h-4 text-gray-500" />
                  ) : (
                    <ChevronDown className="w-4 h-4 text-gray-500" />
                  )}
                </button>
                {isOpen && (
                  <div className="px-5 pb-4 pt-1 text-xs text-gray-600 leading-relaxed border-t border-gray-50">
                    {faq.a}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </section>

      {/* Disclaimer Section */}
      <footer className="w-full bg-[#18181B] text-white py-12 px-6">
        <div className="max-w-4xl mx-auto space-y-4 text-center">
          <h3 className="text-xl font-bold tracking-tight text-white">Disclaimer</h3>
          <p className="text-xs text-gray-400 leading-relaxed max-w-3xl mx-auto">
            MIIA is designed to provide healthcare information, medical document analysis and AI-assisted injury assessment for informational purposes. The information and assessments generated by the platform do not constitute a medical diagnosis, professional medical advice or treatment recommendations. MIIA is not a substitute for consultation, examination or care provided by a qualified healthcare professional. Always consult an appropriate medical professional when making decisions concerning your health.
          </p>
          <div className="pt-6 border-t border-gray-800/80 text-[11px] text-gray-400 text-left">
            © 2026 MIIA. All rights reserved.
          </div>
        </div>
      </footer>
    </div>
  );
}

