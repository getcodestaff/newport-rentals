import { useCallback, useEffect, useState } from 'react';

export type ConnectionDetails = {
  serverUrl: string;
  roomName: string;
  participantName: string;
  participantToken: string;
};

export default function useConnectionDetails() {
  const [connectionDetails, setConnectionDetails] = useState<ConnectionDetails | null>(null);

  const fetchConnectionDetails = useCallback(() => {
    setConnectionDetails(null);
    const getDetails = async () => {
      try {
        // Use the client-side token generation approach
        const resp = await fetch('/api/connection-details');

        if (!resp.ok) {
          const errorBody = await resp.text();
          throw new Error(`Failed to fetch connection details: ${resp.statusText}. Body: ${errorBody}`);
        }

        const data = await resp.json();
        setConnectionDetails(data);
      } catch (error) {
        console.error('Error fetching connection details:', error);
      }
    };
    getDetails();
  }, []);

  useEffect(() => {
    fetchConnectionDetails();
  }, [fetchConnectionDetails]);

  return { connectionDetails, refreshConnectionDetails: fetchConnectionDetails };
}
