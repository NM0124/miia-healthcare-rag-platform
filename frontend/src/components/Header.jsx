import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { LogOut, User as UserIcon } from 'lucide-react';

export default function Header({ activeTab, onTabChange }) {
  const { user, logout, openLogin } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <header className="w-full bg-white border-b border-gray-100 sticky top-0 z-40">
      <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
        {/* Logo: MI²A */}
        <div 
          onClick={() => onTabChange(user ? 'ask' : 'home')}
          className="flex items-center cursor-pointer select-none"
        >
          <span className="text-2xl font-bold tracking-tight text-gray-900">
            MI<sup className="text-sm font-semibold text-gray-900 ml-0.5">2</sup>A
          </span>
        </div>

        {/* Center Nav Tabs (Authenticated) */}
        {user ? (
          <nav className="flex items-center space-x-8">
            <button
              onClick={() => onTabChange('ask')}
              className={`text-sm font-medium transition-colors ${
                activeTab === 'ask'
                  ? 'text-gray-900 font-semibold'
                  : 'text-gray-500 hover:text-gray-800'
              }`}
            >
              Ask
            </button>
            <button
              onClick={() => onTabChange('knowledge-base')}
              className={`text-sm font-medium transition-colors ${
                activeTab === 'knowledge-base'
                  ? 'text-gray-900 font-semibold'
                  : 'text-gray-500 hover:text-gray-800'
              }`}
            >
              Knowledge Base
            </button>
            <button
              onClick={() => onTabChange('injury-analysis')}
              className={`text-sm font-medium transition-colors ${
                activeTab === 'injury-analysis'
                  ? 'text-gray-900 font-semibold'
                  : 'text-gray-500 hover:text-gray-800'
              }`}
            >
              Injury Analysis
            </button>
          </nav>
        ) : (
          <div />
        )}

        {/* Right Action */}
        {user ? (
          <div className="relative">
            <button
              onClick={() => setMenuOpen(!menuOpen)}
              className="flex items-center space-x-2 focus:outline-none"
            >
              {user.picture ? (
                <img
                  src={user.picture}
                  alt={user.name}
                  className="w-9 h-9 rounded-full object-cover border border-gray-200"
                />
              ) : (
                <div className="w-9 h-9 rounded-full bg-gray-900 text-white flex items-center justify-center font-medium text-sm">
                  {user.name ? user.name[0].toUpperCase() : 'U'}
                </div>
              )}
            </button>

            {menuOpen && (
              <div className="absolute right-0 mt-2 w-48 bg-white border border-gray-100 rounded-xl shadow-lg py-1 z-50 animate-in fade-in duration-100">
                <div className="px-4 py-2 border-b border-gray-100">
                  <p className="text-xs text-gray-400">Signed in as</p>
                  <p className="text-sm font-medium text-gray-900 truncate">{user.name}</p>
                  <p className="text-xs text-gray-500 truncate">{user.email}</p>
                </div>
                <button
                  onClick={() => {
                    setMenuOpen(false);
                    logout();
                    onTabChange('home');
                  }}
                  className="w-full text-left px-4 py-2 text-sm text-red-600 hover:bg-gray-50 flex items-center space-x-2"
                >
                  <LogOut className="w-4 h-4" />
                  <span>Log out</span>
                </button>
              </div>
            )}
          </div>
        ) : (
          <div className="flex items-center space-x-6">
            <button
              onClick={openLogin}
              className="text-sm font-medium text-gray-700 hover:text-gray-900 transition-colors"
            >
              Log in
            </button>
            <button
              onClick={openLogin}
              className="bg-gray-900 hover:bg-black text-white text-sm font-medium px-5 py-2.5 rounded-full transition-all shadow-sm hover:shadow"
            >
              Get started
            </button>
          </div>
        )}
      </div>
    </header>
  );
}

