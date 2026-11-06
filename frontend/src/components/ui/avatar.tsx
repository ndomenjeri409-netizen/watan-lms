import { useState, type ImgHTMLAttributes } from 'react'
import { cn } from '../../lib/cn'

export interface AvatarProps extends Omit<ImgHTMLAttributes<HTMLImageElement>, 'src' | 'alt'> {
  src?: string | null
  alt: string
  initials?: string
}

export function Avatar({ src, alt, initials, className, ...props }: AvatarProps) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null)

  if (src && failedSrc !== src) {
    return (
      <img
        src={src}
        alt={alt}
        className={cn('size-10 rounded-full object-cover', className)}
        onError={() => setFailedSrc(src)}
        {...props}
      />
    )
  }

  const fallback = initials ?? alt.trim().split(/\s+/).slice(0, 2).map((part) => part[0]).join('')

  return (
    <span
      className={cn('inline-flex size-10 items-center justify-center rounded-full bg-app text-sm font-semibold text-fg', className)}
      role="img"
      aria-label={alt}
    >
      {fallback.toUpperCase()}
    </span>
  )
}
