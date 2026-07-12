import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { DeviceFrame } from '../src/components/DeviceFrame';

describe('DeviceFrame', () => {
  it('renders browser frame with provided url', () => {
    render(
      <DeviceFrame variant="browser" url="example.com">
        <div>Browser content</div>
      </DeviceFrame>,
    );
    expect(screen.getByText('example.com')).toBeInTheDocument();
    expect(screen.getByText('Browser content')).toBeInTheDocument();
  });

  it('renders browser frame with default url when url is omitted', () => {
    render(
      <DeviceFrame variant="browser">
        <div>Browser content</div>
      </DeviceFrame>,
    );
    expect(screen.getByText('kernelworx.com')).toBeInTheDocument();
  });

  it('renders iphone frame', () => {
    const { container } = render(
      <DeviceFrame variant="iphone">
        <div>iPhone content</div>
      </DeviceFrame>,
    );
    expect(container.querySelector('svg')).toBeInTheDocument();
    expect(screen.getByText('iPhone content')).toBeInTheDocument();
  });

  it('renders android frame', () => {
    const { container } = render(
      <DeviceFrame variant="android">
        <div>Android content</div>
      </DeviceFrame>,
    );
    expect(container.querySelector('svg')).toBeInTheDocument();
    expect(screen.getByText('Android content')).toBeInTheDocument();
  });
});
