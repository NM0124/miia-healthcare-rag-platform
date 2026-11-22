import React, { useState } from 'react';
import { AuthProvider, useAuth } from './context/AuthContext';
import Header from './components/Header';
import LoginModal from './components/LoginModal';
import HomePage from './pages/HomePage';
import AskPage from './pages/AskPage';
import KnowledgeBasePage from './pages/KnowledgeBasePage';
import InjuryAnalysisPage from './pages/InjuryAnalysisPage';

function AppContent() {
  const { user, loading } = useAuth();
  const [activeTab, setActiveTab] = useState('home');

  // If user is logged in and still on home, transition to ask
  React.useEffect(() => {
    if (user && activeTab === 'home') {
      setActiveTab('ask');
    } else if (!user && activeTab !== 'home') {
      setActiveTab('home');
    }
  }, [user]);

  if (loading) {
    return (
      <div className="min-h-screen bg-white flex items-center justify-center">
        <div className="flex items-center space-x-2 text-sm text-gray-500 font-medium">
          <span className="text-xl font-bold tracking-tight text-gray-900">
            MI<sup className="text-xs ml-0.5">2</sup>A
          </span>
          <span className="text-gray-300">|</span>
          <span>Loading platform...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-white flex flex-col font-sans">
      <Header
        activeTab={activeTab}
        onTabChange={(tab) => setActiveTab(tab)}
      />

      <main className="flex-1 w-full">
        {activeTab === 'home' && (
          <HomePage onGetStarted={() => setActiveTab('ask')} />
        )}

        {activeTab === 'ask' && user && (
          <AskPage onNavigateKnowledgeBase={() => setActiveTab('knowledge-base')} />
        )}

        {activeTab === 'knowledge-base' && user && (
          <KnowledgeBasePage />
        )}

        {activeTab === 'injury-analysis' && user && (
          <InjuryAnalysisPage />
        )}
      </main>

      <LoginModal onSuccess={() => setActiveTab('ask')} />
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  );
}

