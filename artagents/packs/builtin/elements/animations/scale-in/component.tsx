import {isValidElement} from 'react';
import type {ReactElement} from 'react';

export default function ScaleIn(props: Record<string, unknown>): ReactElement | null {
  return isValidElement(props.children) ? props.children : null;
}
