import React, { createContext, useContext, useState, useEffect } from 'react';
import { googleLoginApi, fetchCurrentUserApi, logoutApi } from '../api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeSessionId, setActiveSessionId] = useState(null);
  
  // Requirement 2: Knowledge Base sidebar displays ONLY documents uploaded during current active session
  // Clear this temporary list when user logs out or session ends.
  const [sessionUploadedDocs, setSessionUploadedDocs] = useState([]);
  const [showLoginModal, setShowLoginModal] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem('miia_token');
    if (token) {
      fetchCurrentUserApi()
        .then((res) => {
          if (res?.user) {
            setUser(res.user);
          } else {
            localStorage.removeItem('miia_token');
          }
        })
        .catch(() => {
          localStorage.removeItem('miia_token');
        })
        .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, []);

  const loginWithCredential = async (credential) => {
    try {
      const data = await googleLoginApi(credential);
      if (data?.token && data?.user) {
        localStorage.setItem('miia_token', data.token);
        setUser(data.user);
        setSessionUploadedDocs([]); // fresh active session
        setShowLoginModal(false);
        return data.user;
      }
    } catch (err) {
      console.error('Login error:', err);
      throw err;
    }
  };

  const logout = async () => {
    await logoutApi();
    localStorage.removeItem('miia_token');
    setUser(null);
    setActiveSessionId(null);
    setSessionUploadedDocs([]); // clear temporary session documents
  };

  const addSessionDoc = (doc) => {
    setSessionUploadedDocs((prev) => [doc, ...prev]);
  };

  const openLogin = () => setShowLoginModal(true);
  const closeLogin = () => setShowLoginModal(false);

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        activeSessionId,
        setActiveSessionId,
        sessionUploadedDocs,
        addSessionDoc,
        loginWithCredential,
        logout,
        openLogin,
        closeLogin,
        showLoginModal,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}

