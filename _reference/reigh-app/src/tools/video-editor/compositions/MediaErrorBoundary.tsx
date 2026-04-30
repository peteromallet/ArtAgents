import { Component, type ReactNode } from 'react';

type MediaErrorBoundaryProps = {
  clipId: string;
  resetKey: string;
  fallback: ReactNode;
  children: ReactNode;
};

type MediaErrorBoundaryState = {
  hasError: boolean;
};

export class MediaErrorBoundary extends Component<MediaErrorBoundaryProps, MediaErrorBoundaryState> {
  state: MediaErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): MediaErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error) {
    console.error(`[MediaErrorBoundary] clip "${this.props.clipId}" runtime error: ${error.message}`);
  }

  componentDidUpdate(prevProps: MediaErrorBoundaryProps) {
    if (this.state.hasError && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ hasError: false });
    }
  }

  render() {
    return this.state.hasError ? this.props.fallback : this.props.children;
  }
}
