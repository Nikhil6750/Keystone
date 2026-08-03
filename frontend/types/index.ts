export * from './api';

export interface UserProfile {
  id: string;
  email: string;
  name: string;
  avatarUrl?: string;
  role: 'admin' | 'user' | 'member';
  createdAt: string;
}

export type ComponentWithChildren<T = object> = React.FC<T & { children?: React.ReactNode }>;
