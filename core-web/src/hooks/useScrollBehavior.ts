import { useState, useEffect, useCallback } from 'react';
import type { ContentPart } from '../api/client';

interface DisplayMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  content_parts?: ContentPart[];
}

interface UseScrollBehaviorParams {
  messages: DisplayMessage[];
  hasStreamingContent: boolean;
  scrollContainerRef: React.RefObject<HTMLDivElement | null>;
  lastUserMessageRef: React.RefObject<HTMLDivElement | null>;
  streamingRef: React.RefObject<HTMLDivElement | null>;
}

export function useScrollBehavior({
  messages,
  hasStreamingContent,
  scrollContainerRef,
  lastUserMessageRef,
  streamingRef,
}: UseScrollBehaviorParams) {
  const [containerHeight, setContainerHeight] = useState<number | null>(null);
  const [aiResponseTop, setAiResponseTop] = useState(0);
  const [availableAiSpace, setAvailableAiSpace] = useState(0);
  const [streamingHeight, setStreamingHeight] = useState(0);
  const [showScrollButton, setShowScrollButton] = useState(false);

  // Check if user is near bottom of scroll
  const checkScrollPosition = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    const threshold = 100;
    const isNearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < threshold;
    setShowScrollButton(!isNearBottom);
  }, [scrollContainerRef]);

  // Scroll to bottom handler
  const scrollToBottom = useCallback(() => {
    const container = scrollContainerRef.current;
    if (container) {
      container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
    }
  }, [scrollContainerRef]);

  // Listen to scroll events
  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    container.addEventListener('scroll', checkScrollPosition);
    checkScrollPosition();

    return () => container.removeEventListener('scroll', checkScrollPosition);
  }, [checkScrollPosition, scrollContainerRef]);

  // Use ResizeObserver for reliable streaming height tracking
  useEffect(() => {
    const element = streamingRef.current;
    if (!element) {
      setStreamingHeight(0);
      return;
    }

    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setStreamingHeight(entry.contentRect.height);
      }
    });

    resizeObserver.observe(element);
    setStreamingHeight(element.offsetHeight);

    return () => resizeObserver.disconnect();
  }, [hasStreamingContent ? 'streaming' : 'idle']);

  // When user sends a message, calculate fixed container height
  useEffect(() => {
    const lastMessage = messages[messages.length - 1];
    if (lastMessage?.role === 'user' && lastUserMessageRef.current && scrollContainerRef.current) {
      requestAnimationFrame(() => {
        const container = scrollContainerRef.current;
        const element = lastUserMessageRef.current;
        if (container && element) {
          const viewportHeight = container.clientHeight;

          const fixedHeight = element.offsetTop + viewportHeight;
          setContainerHeight(fixedHeight);

          const aiTop = element.offsetTop + element.offsetHeight;
          setAiResponseTop(aiTop);

          setAvailableAiSpace(fixedHeight - aiTop - 160);

          setStreamingHeight(0);

          setTimeout(() => {
            container.scrollTo({ top: element.offsetTop, behavior: 'smooth' });
          }, 10);
        }
      });
    }
  }, [messages, lastUserMessageRef, scrollContainerRef]);

  return {
    containerHeight,
    setContainerHeight,
    aiResponseTop,
    setAiResponseTop,
    availableAiSpace,
    setAvailableAiSpace,
    streamingHeight,
    setStreamingHeight,
    showScrollButton,
    scrollToBottom,
  };
}
