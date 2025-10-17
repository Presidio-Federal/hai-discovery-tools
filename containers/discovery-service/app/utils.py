"""
Utility functions for the discovery service.
"""

import os
import json
import logging
from typing import Dict, Any
from datetime import datetime, date

logger = logging.getLogger(__name__)

# Custom JSON encoder to handle datetime objects
class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        return super().default(obj)

def write_artifact(job_id: str, filename: str, data: Dict[str, Any]) -> str:
    """
    Write data to a file in the job's artifact directory.
    
    Args:
        job_id: The ID of the job
        filename: The name of the file to write
        data: The data to write to the file
        
    Returns:
        The path to the written file
    """
    # Create the directory path
    path = f"/app/data/exports/{job_id}"
    os.makedirs(path, exist_ok=True)
    
    # Create the file path
    file_path = os.path.join(path, filename)
    
    try:
        # Write the data to the file
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2, cls=DateTimeEncoder)
        
        logger.info(f"Wrote artifact to {file_path}")
        return file_path
    
    except Exception as e:
        logger.error(f"Error writing artifact to {file_path}: {str(e)}")
        
        # Try writing to a fallback location
        fallback_path = f"/app/data/exports/{filename}"
        try:
            with open(fallback_path, 'w') as f:
                json.dump(data, f, indent=2, cls=DateTimeEncoder)
            
            logger.info(f"Wrote artifact to fallback path {fallback_path}")
            return fallback_path
        
        except Exception as e2:
            logger.error(f"Error writing artifact to fallback path {fallback_path}: {str(e2)}")
            return ""
