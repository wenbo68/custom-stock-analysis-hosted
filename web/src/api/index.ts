import axios from 'axios';
import { API_BASE_URL } from '../utils/constants';
import { attachParsedApiError } from './error';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
});

// No auth in the standalone app, so no 401 login redirect — errors are
// only parsed into a readable message.
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    attachParsedApiError(error);
    return Promise.reject(error);
  }
);

export default apiClient;
