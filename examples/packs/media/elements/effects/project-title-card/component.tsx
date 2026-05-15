import React from 'react';

interface ProjectTitleCardProps {
  title?: string;
}

const ProjectTitleCard: React.FC<ProjectTitleCardProps> = ({ title = 'My Project' }) => {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: '100%',
        height: '100%',
        backgroundColor: '#1a1a2e',
        color: '#e94560',
        fontFamily: 'sans-serif',
        fontSize: 64,
        fontWeight: 'bold',
      }}
    >
      {title}
    </div>
  );
};

export default ProjectTitleCard;
