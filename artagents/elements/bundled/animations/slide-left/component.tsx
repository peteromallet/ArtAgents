import {isValidElement} from 'react';
import type {ReactElement} from 'react';

export default function SlideLeft(props: Record<string, unknown>): ReactElement | null {
  return isValidElement(props.children) ? props.children : null;
}
