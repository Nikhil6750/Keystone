import { redirect } from 'next/navigation';

/**
 * `/workspace` was an early, unlinked duplicate of `/chat`'s workflow-creation
 * flow. Rather than maintain two diverging workspaces, this route now simply
 * redirects to `/chat`, the single guided entry point.
 */
export default function WorkspaceRedirectPage() {
  redirect('/chat');
}
