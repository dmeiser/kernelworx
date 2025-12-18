/**
 * GraphQL error handler for toast notifications
 *
 * Listens for graphql-error events and displays user-friendly toast messages.
 * This module is used by the AppLayout component to show error toasts.
 */

export interface GraphQLErrorEvent {
  errorCode: string;
  message: string;
  operation: string;
}

/**
 * Setup GraphQL error listener
 *
 * @param onError Callback to display error toast
 * @returns Cleanup function to remove listener
 */
export function setupGraphQLErrorListener(
  onError: (error: GraphQLErrorEvent) => void,
): () => void {
  const handler = (event: Event) => {
    const customEvent = event as CustomEvent<GraphQLErrorEvent>;
    onError(customEvent.detail);
  };

  window.addEventListener("graphql-error", handler);

  return () => {
    window.removeEventListener("graphql-error", handler);
  };
}
