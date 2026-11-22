import React, { useEffect, useRef } from 'react';
import { useAuth } from '../context/AuthContext';
import { X } from 'lucide-react';

export default function LoginModal({ onSuccess }) {
  const { showLoginModal, closeLogin, loginWithCredential } = useAuth();
  const googleBtnRef = useRef(null);

  useEffect(() => {
    if (!showLoginModal) return;

    const clientId =
      import.meta.env.VITE_GOOGLE_CLIENT_ID ||
      import.meta.env.GOOGLE_CLIENT_ID ||
      '';

    // Initialize Google Identity Services if available and configured
    if (window.google?.accounts?.id && clientId) {
      window.google.accounts.id.initialize({
        client_id: clientId,
        callback: async (response) => {
          if (response.credential) {
            try {
              await loginWithCredential(response.credential);
              if (onSuccess) onSuccess();
            } catch (err) {
              alert('Google Sign-In failed. Please try again.');
            }
          }
        },
      });

      if (googleBtnRef.current) {
        window.google.accounts.id.renderButton(googleBtnRef.current, {
          theme: 'outline',
          size: 'large',
          width: 320,
          text: 'signin_with',
          shape: 'pill',
        });
      }
    }
  }, [showLoginModal]);

  if (!showLoginModal) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm animate-in fade-in duration-150">
      <div className="bg-white rounded-2xl shadow-2xl border border-gray-100 max-w-sm w-full mx-4 p-8 relative">
        <button
          onClick={closeLogin}
          className="absolute top-5 right-5 text-gray-400 hover:text-gray-600 transition-colors"
        >
          <X className="w-5 h-5" />
        </button>

        <div className="text-center mb-6">
          <span className="text-3xl font-bold tracking-tight text-gray-900">
            MI<sup className="text-base font-semibold ml-0.5">2</sup>A
          </span>
          <h3 className="text-xl font-bold text-gray-900 mt-3">Welcome to MIIA</h3>
          <p className="text-xs text-gray-500 mt-1.5 leading-relaxed">
            Evidence-grounded medical intelligence & document analysis platform
          </p>
        </div>

        {/* Google OAuth Render Button */}
        <div className="flex flex-col items-center justify-center space-y-4 my-6">
          <div ref={googleBtnRef} className="flex justify-center w-full min-h-[44px]"></div>
        </div>

        <p className="text-[11px] text-gray-400 text-center leading-normal mt-4">
          By signing in, you agree to MIIA's Terms of Service and Privacy Policy.
        </p>
      </div>
    </div>
  );
}

